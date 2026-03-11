from __future__ import annotations

from .types import AudioFormat

LISTEN_AUDIO_FORMAT = AudioFormat(
    sample_rate_hz=16000,
    channels=1,
    sample_width=2,
)
LISTEN_LANGUAGE_CODE = "ja-JP"

__all__ = ["LISTEN_AUDIO_FORMAT", "LISTEN_LANGUAGE_CODE"]
