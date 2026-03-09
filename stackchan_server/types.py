from __future__ import annotations

from typing import Protocol


class SpeechRecognizer(Protocol):
    def transcribe(
        self,
        pcm_bytes: bytes,
        *,
        sample_rate_hz: int,
        channels: int,
        sample_width: int,
        language_code: str = "ja-JP",
    ) -> str: ...


__all__ = ["SpeechRecognizer"]
