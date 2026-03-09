from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SpeechRecognizer(Protocol):
    async def transcribe(
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
    async def push_audio(self, pcm_bytes: bytes) -> None: ...

    async def finish(self) -> str: ...

    async def abort(self) -> None: ...


@runtime_checkable
class StreamingSpeechRecognizer(SpeechRecognizer, Protocol):
    async def start_stream(
        self,
        *,
        sample_rate_hz: int,
        channels: int,
        sample_width: int,
        language_code: str = "ja-JP",
    ) -> StreamingSpeechSession: ...


__all__ = ["SpeechRecognizer", "StreamingSpeechRecognizer", "StreamingSpeechSession"]


@runtime_checkable
class SpeechSynthesizer(Protocol):
    async def synthesize(self, text: str) -> bytes: ...


__all__ = [
    "SpeechRecognizer",
    "StreamingSpeechRecognizer",
    "StreamingSpeechSession",
    "SpeechSynthesizer",
]
