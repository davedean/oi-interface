"""
server/stt.py — local speech-to-text via faster-whisper.

Lazy model load: the WhisperModel is created on the first transcribe() call
and cached for subsequent calls. Model: base.en (~140 MB, ~400 MB RAM).

Install: pip3 install faster-whisper
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile

_model = None  # cached WhisperModel

# Diagnostic: last received WAV is copied here for offline playback/inspection.
DEBUG_WAV_PATH = "/tmp/oi-last-audio.wav"


class SttUnavailable(Exception):
    """Raised when the STT backend (faster-whisper) is not installed."""


def transcribe(wav_bytes: bytes) -> str:
    """Transcribe WAV bytes, return transcript string (may be empty)."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
        # Keep a copy for offline inspection (overwritten each call).
        shutil.copy2(tmp_path, DEBUG_WAV_PATH)
        print(
            f"[stt] audio received: {len(wav_bytes)} bytes → {DEBUG_WAV_PATH}",
            flush=True,
        )
        return _run(tmp_path)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass


_LEADING_FILLERS = re.compile(r'^(?:(?:um+|uh+|hmm+|ah+|er+)\b\s*[,.]?\s*)+', re.IGNORECASE)


def clean_transcript(raw: str) -> str:
    """Minimal cleanup of Whisper output for prompt consumption.

    Only removes leading filler sounds that are almost certainly
    transcription artifacts, not meaningful content words like "like".
    """
    text = raw.strip()
    if not text:
        return text
    # Remove leading fillers (e.g., "um, can you help" → "can you help")
    text = _LEADING_FILLERS.sub('', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Add trailing period if no terminal punctuation
    if text and text[-1] not in '.!?':
        text += '.'
    return text


_MODEL_NAME = "base.en"


def _run(wav_path: str) -> str:
    global _model
    import time
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SttUnavailable(
            "faster-whisper not installed; run: pip3 install faster-whisper"
        )
    if _model is None:
        t0 = time.monotonic()
        _model = WhisperModel(_MODEL_NAME, device="cpu", compute_type="int8")
        print(f"[stt] model {_MODEL_NAME!r} loaded in {time.monotonic()-t0:.1f}s", flush=True)
    t0 = time.monotonic()
    segments, info = _model.transcribe(wav_path, beam_size=5, language="en")
    parts = []
    for s in segments:
        print(
            f"[stt] segment [{s.start:.1f}s–{s.end:.1f}s] "
            f"no_speech_prob={s.no_speech_prob:.2f}: {s.text.strip()!r}",
            file=sys.stderr,
            flush=True,
        )
        parts.append(s.text.strip())
    elapsed = time.monotonic() - t0
    transcript = " ".join(parts).strip()
    print(f"[stt] transcript ({_MODEL_NAME}, {elapsed:.2f}s): {transcript!r}", flush=True)
    return transcript
