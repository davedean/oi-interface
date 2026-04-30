from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from audio.stt import FasterWhisperBackend, OpenAiWhisperBackend, SttMetrics


def test_stt_metrics_to_dict():
    metrics = SttMetrics(1.0, 5, 2, "en", "m", 100.0)
    data = metrics.to_dict()
    assert data["duration_seconds"] == 1.0
    assert data["realtime_factor"] == 0.1


def test_faster_whisper_backend_import_error():
    with patch.dict("sys.modules", {"faster_whisper": None}):
        with pytest.raises(ImportError, match="faster-whisper"):
            FasterWhisperBackend()


def test_faster_whisper_backend_transcribe_and_simple(monkeypatch):
    class Segment:
        def __init__(self, text):
            self.text = text

    class Model:
        def __init__(self, model, device, compute_type):
            self.init_args = (model, device, compute_type)

        def transcribe(self, wav_io, **kwargs):
            assert isinstance(wav_io, io.BytesIO)
            assert kwargs["language"] == "en"
            assert kwargs["beam_size"] == 5
            return [Segment(" hello "), Segment("world ")], SimpleNamespace(language="en")

    class Module:
        WhisperModel = Model

    with patch.dict("sys.modules", {"faster_whisper": Module}):
        backend = FasterWhisperBackend(model="base.en", device="cpu", compute_type="int8")
        text, metrics = backend.transcribe(b"\x00\x01" * 16000, sample_rate=16000)
        assert text == "hello world"
        assert metrics.language == "en"
        assert metrics.model == "base.en"
        assert backend.transcribe_simple(b"\x00\x01", sample_rate=16000) == "hello world"


def test_openai_whisper_backend_requires_key_and_builds_request():
    with pytest.raises(ValueError, match="API key"):
        OpenAiWhisperBackend(api_key="")

    backend = OpenAiWhisperBackend(api_key="secret", model="m")

    class Resp:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return None
        def read(self):
            return json.dumps({"text": "hello world"}).encode("utf-8")

    with patch("audio.stt.urllib.request.urlopen", return_value=Resp()) as mock_urlopen:
        text, metrics = backend.transcribe(b"\x00\x01" * 8000, sample_rate=16000)
        assert text == "hello world"
        assert metrics.word_count == 2
        request = mock_urlopen.call_args.args[0]
        assert request.headers["Authorization"] == "Bearer secret"
        assert "multipart/form-data" in request.headers["Content-type"]
        assert request.full_url.endswith("/audio/transcriptions")
