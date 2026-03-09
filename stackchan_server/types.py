from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
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


@runtime_checkable
class StreamingSpeechSession(Protocol):
    def push_audio(self, pcm_bytes: bytes) -> None: ...

    def finish(self) -> str: ...

    def abort(self) -> None: ...


@runtime_checkable
class StreamingSpeechRecognizer(SpeechRecognizer, Protocol):
    def start_stream(
        self,
        *,
        sample_rate_hz: int,
        channels: int,
        sample_width: int,
        language_code: str = "ja-JP",
    ) -> StreamingSpeechSession: ...


__all__ = ["SpeechRecognizer", "StreamingSpeechRecognizer", "StreamingSpeechSession"]
