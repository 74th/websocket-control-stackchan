from __future__ import annotations

import asyncio
import unicodedata
from logging import getLogger

from pydantic import Field
from pydantic_settings import BaseSettings

from ..speech_recognition.whisper_server import (
    WhisperServerSpeechToText,
    WhisperServerSpeechToTextConfig,
)
from ..static import LISTEN_AUDIO_FORMAT

logger = getLogger(__name__)


class WakeWordDetectionError(Exception):
    pass


class WhisperServerWakeWordDetectorConfig(BaseSettings):
    keywords: list[str] = Field(default_factory=lambda: ["スタックチャン"])
    window_seconds: float = 3.0
    interval_seconds: float = 0.5
    timeout_seconds: float = 30.0

    class Config:
        env_prefix = "STACKCHAN_WWD_"


class WhisperServerWakeWordSpeechToTextConfig(WhisperServerSpeechToTextConfig):
    class Config(WhisperServerSpeechToTextConfig.Config):
        env_prefix = "STACKCHAN_WWD_WHISPER_SERVER_"


class WhisperServerWakeWordDetector:
    def __init__(
        self,
        *,
        recognizer: WhisperServerSpeechToText | None = None,
        config: WhisperServerWakeWordDetectorConfig | None = None,
    ) -> None:
        self.config = config or WhisperServerWakeWordDetectorConfig()
        self.recognizer = recognizer or WhisperServerSpeechToText(
            config=WhisperServerWakeWordSpeechToTextConfig()
        )
        self._pcm_buffer = bytearray()
        self._running = False
        self._detected = False
        self._streaming_started = False
        self._error: Exception | None = None
        self._last_inference_at = 0.0
        self._inference_task: asyncio.Task[None] | None = None
        self._event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._streaming_ended = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        await self.stop()
        self._pcm_buffer = bytearray()
        self._running = True
        self._detected = False
        self._streaming_started = False
        self._streaming_ended = False
        self._error = None
        self._last_inference_at = 0.0
        self._event.clear()
        logger.info("Server-side wake-word detection started")

    async def stop(self) -> None:
        self._running = False
        if self._inference_task is not None:
            self._inference_task.cancel()
            try:
                await self._inference_task
            except asyncio.CancelledError:
                pass
            self._inference_task = None
        self._event.set()

    async def handle_start(self) -> None:
        if not self._running:
            return
        self._streaming_started = True
        self._streaming_ended = False
        self._pcm_buffer = bytearray()
        self._last_inference_at = 0.0
        logger.info("Server-side wake-word stream START")

    async def handle_data(self, payload: bytes) -> None:
        if not self._running:
            return
        if not self._streaming_started:
            logger.warning(
                "Ignoring stale server-side wake-word DATA before START payload_bytes=%d",
                len(payload),
            )
            return
        if self._streaming_ended:
            logger.warning(
                "Ignoring stale server-side wake-word DATA after END payload_bytes=%d",
                len(payload),
            )
            return

        self._pcm_buffer.extend(payload)
        self._truncate_buffer_to_window()

        loop = asyncio.get_running_loop()
        now = loop.time()
        if (now - self._last_inference_at) < self.config.interval_seconds:
            return
        if self._inference_task is not None and not self._inference_task.done():
            return

        self._last_inference_at = now
        window_bytes = bytes(self._pcm_buffer)
        self._inference_task = asyncio.create_task(self._run_inference(window_bytes))

    async def handle_end(self) -> None:
        if not self._running:
            return
        if not self._streaming_started:
            logger.warning("Ignoring stale server-side wake-word END before START")
            return
        if self._streaming_ended:
            logger.warning("Ignoring duplicate server-side wake-word END")
            return
        self._streaming_ended = True
        logger.info("Server-side wake-word stream END")
        if self._inference_task is not None and not self._inference_task.done():
            try:
                await self._inference_task
            except Exception as exc:  # pragma: no cover
                self._error = exc
        if not self._detected:
            self._event.set()

    async def wait_result(self, timeout_seconds: float | None = None) -> bool:
        if not self._running:
            raise WakeWordDetectionError("Server-side wake-word detection is not running")

        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self.config.timeout_seconds
        )
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise WakeWordDetectionError("Server-side wake-word detection timed out") from exc

        if self._error is not None:
            raise WakeWordDetectionError(str(self._error)) from self._error

        return self._detected

    async def _run_inference(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return

        try:
            async with self._lock:
                transcript = await self.recognizer.transcribe(pcm_bytes)
        except Exception as exc:  # pragma: no cover
            logger.exception("Server-side wake-word transcription failed")
            self._error = exc
            self._event.set()
            return

        logger.info("Server-side wake-word transcript: %s", transcript)

        if self._contains_wake_word(transcript):
            logger.info("Server-side wake-word detected")
            self._detected = True
            self._event.set()

    def _contains_wake_word(self, transcript: str) -> bool:
        normalized_transcript = _normalize_text(transcript)
        if not normalized_transcript:
            return False

        for keyword in self.config.keywords:
            normalized_keyword = _normalize_text(keyword)
            if normalized_keyword and normalized_keyword in normalized_transcript:
                return True
        return False

    def _truncate_buffer_to_window(self) -> None:
        sample_rate = LISTEN_AUDIO_FORMAT.sample_rate_hz
        channels = LISTEN_AUDIO_FORMAT.channels
        sample_width = LISTEN_AUDIO_FORMAT.sample_width
        bytes_per_second = sample_rate * channels * sample_width
        max_bytes = max(1, int(bytes_per_second * self.config.window_seconds))
        if len(self._pcm_buffer) <= max_bytes:
            return
        del self._pcm_buffer[: len(self._pcm_buffer) - max_bytes]


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    return "".join(normalized.lower().split())


__all__ = [
    "WhisperServerWakeWordDetector",
    "WhisperServerWakeWordDetectorConfig",
    "WhisperServerWakeWordSpeechToTextConfig",
    "WakeWordDetectionError",
]