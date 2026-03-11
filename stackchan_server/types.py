from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class SpeechRecognizer(Protocol):
    async def transcribe(self, pcm_bytes: bytes) -> str: ...


@runtime_checkable
class StreamingSpeechSession(Protocol):
    async def push_audio(self, pcm_bytes: bytes) -> None: ...

    async def finish(self) -> str: ...

    async def abort(self) -> None: ...


@runtime_checkable
class StreamingSpeechRecognizer(SpeechRecognizer, Protocol):
    async def start_stream(self) -> StreamingSpeechSession: ...


@runtime_checkable
class SpeechSynthesizer(Protocol):
    async def synthesize(self, text: str) -> bytes: ...


@dataclass(frozen=True)
class AudioFormat:
    sample_rate_hz: int
    channels: int
    sample_width: int


@runtime_checkable
class StreamingSpeechSynthesizer(SpeechSynthesizer, Protocol):
    @property
    def output_format(self) -> AudioFormat: ...

    def synthesize_stream(self, text: str) -> AsyncIterator[bytes]: ...


__all__ = [
    "AudioFormat",
    "SpeechRecognizer",
    "StreamingSpeechRecognizer",
    "StreamingSpeechSession",
    "SpeechSynthesizer",
    "StreamingSpeechSynthesizer",
]
