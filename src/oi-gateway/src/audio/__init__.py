"""Audio: STT/TTS pipeline and backend abstractions."""
from .delivery import AudioDeliveryPipeline
from .pipeline import StreamAccumulator
from .stt import (
    FasterWhisperBackend,
    OpenAiWhisperBackend,
    SttMetrics,
    StubSttBackend,
    clean_transcript,
    pcm_to_wav,
)
from .tts import (
    AudioQualityMetrics,
    AudioValidationResult,
    EspeakNgTtsBackend,
    OpenAiTtsBackend,
    PiperTtsBackend,
    StubTtsBackend,
    TtsBackend,
    TtsMetrics,
    calculate_quality_metrics,
    detect_silence,
    encode_pcm_to_base64,
    generate_response_id,
    log_audio_metrics,
    text_to_wav,
    trim_silence,
    validate_pcm_format,
    validate_wav_format,
)

__all__ = [
    # Delivery pipeline
    "AudioDeliveryPipeline",
    # STT
    "FasterWhisperBackend",
    "OpenAiWhisperBackend",
    "SttMetrics",
    "StubSttBackend",
    "StreamAccumulator",
    "clean_transcript",
    "pcm_to_wav",
    # TTS
    "AudioQualityMetrics",
    "AudioValidationResult",
    "EspeakNgTtsBackend",
    "OpenAiTtsBackend",
    "PiperTtsBackend",
    "StubTtsBackend",
    "TtsBackend",
    "TtsMetrics",
    "calculate_quality_metrics",
    "detect_silence",
    "encode_pcm_to_base64",
    "generate_response_id",
    "log_audio_metrics",
    "text_to_wav",
    "trim_silence",
    "validate_pcm_format",
    "validate_wav_format",
]
