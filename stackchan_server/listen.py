from __future__ import annotations

import asyncio
import wave
from datetime import UTC, datetime
from logging import getLogger
from pathlib import Path
from typing import Awaitable, Callable, Optional

from fastapi import WebSocket, WebSocketDisconnect

from .types import SpeechRecognizer, StreamingSpeechRecognizer, StreamingSpeechSession

logger = getLogger(__name__)


class TimeoutError(Exception):
    pass


class EmptyTranscriptError(Exception):
    pass


class ListenHandler:
    def __init__(
        self,
        *,
        speech_recognizer: SpeechRecognizer,
        recordings_dir: Path,
        debug_recording: bool,
        sample_rate_hz: int,
        channels: int,
        sample_width: int,
        listen_audio_timeout_seconds: float,
        language_code: str = "ja-JP",
    ) -> None:
        self.speech_recognizer = speech_recognizer
        self.recordings_dir = recordings_dir
        self.debug_recording = debug_recording
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels
        self.sample_width = sample_width
        self.listen_audio_timeout_seconds = listen_audio_timeout_seconds
        self.language_code = language_code

        self._pcm_buffer = bytearray()
        self._streaming = False
        self._pcm_data_counter = 0
        self._message_ready = asyncio.Event()
        self._message_error: Optional[Exception] = None
        self._transcript: Optional[str] = None
        self._speech_stream: Optional[StreamingSpeechSession] = None

    async def close(self) -> None:
        await self._abort_speech_stream()

    async def listen(
        self,
        *,
        send_state_command: Callable[[int], Awaitable[None]],
        is_closed: Callable[[], bool],
        idle_state: int,
        listening_state: int,
    ) -> str:
        await send_state_command(listening_state)
        loop = asyncio.get_running_loop()
        last_counter = self._pcm_data_counter
        last_data_time = loop.time()
        while True:
            if self._message_error is not None:
                err = self._message_error
                self._message_error = None
                raise err
            if self._message_ready.is_set():
                text = self._transcript or ""
                self._transcript = None
                self._message_ready.clear()
                return text
            if is_closed():
                raise WebSocketDisconnect()
            if self._pcm_data_counter != last_counter:
                last_counter = self._pcm_data_counter
                last_data_time = loop.time()
            if (loop.time() - last_data_time) >= self.listen_audio_timeout_seconds:
                if not is_closed():
                    await send_state_command(idle_state)
                raise TimeoutError("Timed out after audio data inactivity from firmware")
            await asyncio.sleep(0.05)

    async def handle_start(self, websocket: WebSocket) -> bool:
        logger.info("Received START")
        await self._abort_speech_stream()
        self._pcm_buffer = bytearray()
        self._streaming = True
        self._message_error = None
        if isinstance(self.speech_recognizer, StreamingSpeechRecognizer):
            try:
                self._speech_stream = await self.speech_recognizer.start_stream(
                    sample_rate_hz=self.sample_rate_hz,
                    channels=self.channels,
                    sample_width=self.sample_width,
                    language_code=self.language_code,
                )
            except Exception:
                asyncio.create_task(websocket.close(code=1011, reason="speech streaming failed"))
                return False
        return True

    async def handle_data(self, websocket: WebSocket, payload_bytes: int, payload: bytes) -> bool:
        logger.info("Received DATA payload_bytes=%d", payload_bytes)
        if not self._streaming:
            await self._abort_speech_stream()
            asyncio.create_task(websocket.close(code=1003, reason="data received before start"))
            return False
        if payload_bytes % (self.sample_width * self.channels) != 0:
            await self._abort_speech_stream()
            asyncio.create_task(websocket.close(code=1003, reason="invalid pcm chunk length"))
            return False
        self._pcm_buffer.extend(payload)
        if payload_bytes > 0:
            try:
                await self._push_speech_stream(payload)
            except Exception:
                await self._abort_speech_stream()
                asyncio.create_task(websocket.close(code=1011, reason="speech streaming failed"))
                return False
            self._pcm_data_counter += 1
        return True

    async def handle_end(
        self,
        websocket: WebSocket,
        *,
        payload_bytes: int,
        payload: bytes,
        send_state_command: Callable[[int], Awaitable[None]],
        thinking_state: int,
    ) -> None:
        logger.info("Received END payload_bytes=%d", payload_bytes)
        if not self._streaming:
            await self._abort_speech_stream()
            await websocket.close(code=1003, reason="end received before start")
            return
        if payload_bytes % (self.sample_width * self.channels) != 0:
            await self._abort_speech_stream()
            await websocket.close(code=1003, reason="invalid pcm tail length")
            return
        self._pcm_buffer.extend(payload)
        if payload_bytes > 0:
            try:
                await self._push_speech_stream(payload)
            except Exception:
                await self._abort_speech_stream()
                await websocket.close(code=1011, reason="speech streaming failed")
                return

        if len(self._pcm_buffer) == 0 or len(self._pcm_buffer) % (self.sample_width * self.channels) != 0:
            await self._abort_speech_stream()
            await websocket.close(code=1003, reason="invalid accumulated pcm length")
            return

        await send_state_command(thinking_state)

        frames = len(self._pcm_buffer) // (self.sample_width * self.channels)
        duration_seconds = frames / float(self.sample_rate_hz)
        ws_meta = {
            "sample_rate": self.sample_rate_hz,
            "frames": frames,
            "channels": self.channels,
            "duration_seconds": round(duration_seconds, 3),
        }
        if self.debug_recording:
            _filepath, filename = self._save_wav(bytes(self._pcm_buffer))
            ws_meta["text"] = f"Saved as {filename}"
            ws_meta["path"] = f"recordings/{filename}"
        else:
            ws_meta["text"] = "Recording skipped (DEBUG_RECODING!=1)"

        await websocket.send_json(ws_meta)

        transcript = await self._transcribe_async(bytes(self._pcm_buffer))

        self._streaming = False
        self._pcm_buffer = bytearray()

        if transcript.strip() == "":
            self._message_error = EmptyTranscriptError("Speech recognition result is empty")
            return

        self._transcript = transcript
        self._message_ready.set()

    def _save_wav(self, pcm_bytes: bytes) -> tuple[Path, str]:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"rec_ws_{timestamp}.wav"
        filepath = self.recordings_dir / filename

        with wave.open(str(filepath), "wb") as wav_fp:
            wav_fp.setnchannels(self.channels)
            wav_fp.setsampwidth(self.sample_width)
            wav_fp.setframerate(self.sample_rate_hz)
            wav_fp.writeframes(pcm_bytes)

        logger.info("Saved WAV: %s", filename)
        return filepath, filename

    async def _transcribe_async(self, pcm_bytes: bytes) -> str:
        if self._speech_stream is not None:
            return await self._finish_speech_stream()
        return await self._transcribe(pcm_bytes)

    async def _transcribe(self, pcm_bytes: bytes) -> str:
        transcript = await self.speech_recognizer.transcribe(
            pcm_bytes,
            sample_rate_hz=self.sample_rate_hz,
            channels=self.channels,
            sample_width=self.sample_width,
            language_code=self.language_code,
        )
        if transcript:
            logger.info("Transcript: %s", transcript)
        return transcript

    async def _push_speech_stream(self, pcm_bytes: bytes) -> None:
        if self._speech_stream is not None:
            await self._speech_stream.push_audio(pcm_bytes)

    async def _finish_speech_stream(self) -> str:
        speech_stream = self._speech_stream
        self._speech_stream = None
        if speech_stream is None:
            return ""
        transcript = await speech_stream.finish()
        if transcript:
            logger.info("Transcript: %s", transcript)
        return transcript

    async def _abort_speech_stream(self) -> None:
        speech_stream = self._speech_stream
        self._speech_stream = None
        if speech_stream is not None:
            await speech_stream.abort()


__all__ = ["ListenHandler", "TimeoutError", "EmptyTranscriptError"]
