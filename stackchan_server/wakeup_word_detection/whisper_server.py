from __future__ import annotations

import asyncio
import unicodedata
from logging import getLogger
from typing import Any

from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings

from ..speech_recognition.whisper_server import (
    WhisperServerSpeechToText,
    WhisperServerSpeechToTextConfig,
)
from ..static import LISTEN_AUDIO_FORMAT

logger = getLogger(__name__)


class WakeWordDetectionError(Exception):
    pass


class WakeWordDetectionTimeout(WakeWordDetectionError):
    pass


class WhisperServerWakeWordDetectorConfig(BaseSettings):
    keywords: list[str] = ["スタックチャン"]
    window_seconds: float = 3.0
    min_buffer_seconds: float = 1.0
    interval_seconds: float = 0.5
    timeout_seconds: float = 300.0
    ignore_detected: str = ""

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        if field_name == 'keywords':
            return [x.strip() for x in value.split(',') if x.strip()]
        return value

    class Config:
        env_prefix = "STACKCHAN_WWD_WHISPER_SERVER_"



class WhisperServerWakeWordSpeechToTextConfig(WhisperServerSpeechToTextConfig):
    class Config(WhisperServerSpeechToTextConfig.Config):
        env_prefix = "STACKCHAN_WWD_WHISPER_SERVER_"


class WhisperServerWakeWordDetector:
    def __init__(
        self,
        *,
        recognizer: WhisperServerSpeechToText | None = None,
        config: WhisperServerWakeWordDetectorConfig | None = None,
        recognizer_config: WhisperServerWakeWordSpeechToTextConfig | None = None,
    ) -> None:
        self.config = config or WhisperServerWakeWordDetectorConfig()
        self.recognizer_config = recognizer_config or WhisperServerWakeWordSpeechToTextConfig()
        self.recognizer = recognizer or WhisperServerSpeechToText(config=self.recognizer_config)
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
        if not payload:
            return

        self._pcm_buffer.extend(payload)
        self._truncate_buffer_to_window()

        buffered_seconds = self._pcm_duration_seconds(len(self._pcm_buffer))
        if buffered_seconds < self.config.min_buffer_seconds:
            return

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
            raise WakeWordDetectionTimeout(
                "Server-side wake-word detection timed out"
            ) from exc

        if self._error is not None:
            raise WakeWordDetectionError(str(self._error)) from self._error

        return self._detected

    async def _run_inference(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return

        if self._pcm_duration_seconds(len(pcm_bytes)) < self.config.min_buffer_seconds:
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

        if self.config.ignore_detected and self.config.ignore_detected in normalized_transcript:
            # If the ignore_detected phrase is included in the transcript, it may indicate that the transcription is not accurate or that the model is confused. In this case, we choose to ignore the transcript to avoid false positives.
            return False
        for keyword in self.config.keywords:
            normalized_keyword = _normalize_text(keyword)
            if normalized_keyword and normalized_keyword in normalized_transcript:
                return True
        return False

    def _truncate_buffer_to_window(self) -> None:
        bytes_per_second = self._pcm_bytes_per_second()
        max_bytes = max(1, int(bytes_per_second * self.config.window_seconds))
        if len(self._pcm_buffer) <= max_bytes:
            return
        del self._pcm_buffer[: len(self._pcm_buffer) - max_bytes]

    def _pcm_bytes_per_second(self) -> int:
        sample_rate = LISTEN_AUDIO_FORMAT.sample_rate_hz
        channels = LISTEN_AUDIO_FORMAT.channels
        sample_width = LISTEN_AUDIO_FORMAT.sample_width
        return sample_rate * channels * sample_width

    def _pcm_duration_seconds(self, pcm_byte_length: int) -> float:
        bytes_per_second = self._pcm_bytes_per_second()
        if bytes_per_second <= 0:
            return 0.0
        return pcm_byte_length / float(bytes_per_second)


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    return "".join(normalized.lower().split())


__all__ = [
    "WhisperServerWakeWordDetector",
    "WhisperServerWakeWordDetectorConfig",
    "WhisperServerWakeWordSpeechToTextConfig",
    "WakeWordDetectionError",
    "WakeWordDetectionTimeout",
]
