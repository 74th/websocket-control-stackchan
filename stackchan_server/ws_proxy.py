from __future__ import annotations

import asyncio
import io
import struct
import wave
from contextlib import suppress
from datetime import datetime
from logging import getLogger
from pathlib import Path
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from google.cloud import speech
from vvclient import Client as VVClient

logger = getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent
_RECORDINGS_DIR = _BASE_DIR / "recordings"
_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

_WS_HEADER_FMT = "<BBBHH"  # kind, msg_type, reserved, seq, payload_bytes
_WS_HEADER_SIZE = struct.calcsize(_WS_HEADER_FMT)
_WS_KIND_PCM = 1
_WS_KIND_WAV = 2
_WS_KIND_STATE_CMD = 3
_WS_KIND_WAKEWORD_EVT = 4
_WS_KIND_STATE_EVT = 5
_WS_KIND_SPEAK_DONE_EVT = 6
_WS_MSG_START = 1
_WS_MSG_DATA = 2
_WS_MSG_END = 3

_STATE_IDLE = 0
_STATE_LISTENING = 1
_STATE_THINKING = 2

_SAMPLE_RATE_HZ = 16000
_CHANNELS = 1
_SAMPLE_WIDTH = 2  # bytes

_DOWN_WAV_CHUNK = 4096  # bytes per WebSocket frame for synthesized audio (raw PCM)
_DOWN_SEGMENT_MILLIS = 2000  # duration of a single START-DATA-END segment in milliseconds
_DOWN_SEGMENT_STAGGER_MILLIS = _DOWN_SEGMENT_MILLIS // 2  # half interval for the second segment start
_LISTEN_AUDIO_TIMEOUT_SECONDS = 10.0


class TimeoutError(Exception):
    pass


class EmptyTranscriptError(Exception):
    pass


def create_voicevox_client() -> VVClient:
    return VVClient(base_uri="http://localhost:50021")


class WsProxy:
    def __init__(self, websocket: WebSocket, speech_client: speech.SpeechClient):
        self.ws = websocket
        self.speech_client = speech_client
        self.recordings_dir = _RECORDINGS_DIR
        self.recordings_dir.mkdir(parents=True, exist_ok=True)

        self._pcm_buffer = bytearray()
        self._streaming = False
        self._pcm_data_counter = 0
        self._message_ready = asyncio.Event()
        self._message_error: Optional[Exception] = None
        self._transcript: Optional[str] = None
        self._wakeword_event = asyncio.Event()

        self._receiving_task: Optional[asyncio.Task] = None
        self._closed = False

        self._speaking = False
        self._speak_finished_counter = 0

        self._down_seq = 0

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def receive_task(self) -> Optional[asyncio.Task]:
        return self._receiving_task

    async def wait_for_talk_session(self) -> None:
        while True:
            if self._wakeword_event.is_set():
                self._wakeword_event.clear()
                return
            if self._closed:
                raise WebSocketDisconnect()
            await asyncio.sleep(0.05)

    async def listen(self) -> str:
        await self.send_state_command(_STATE_LISTENING)
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
            if self._closed:
                raise WebSocketDisconnect()
            if self._pcm_data_counter != last_counter:
                last_counter = self._pcm_data_counter
                last_data_time = loop.time()
            if (loop.time() - last_data_time) >= _LISTEN_AUDIO_TIMEOUT_SECONDS:
                if not self._closed:
                    await self.send_state_command(_STATE_IDLE)
                raise TimeoutError("Timed out after audio data inactivity from firmware")
            await asyncio.sleep(0.05)

    async def speak(self, text: str) -> None:
        start_counter = self._speak_finished_counter
        await self._start_talking_stream(text)
        if not self._speaking:
            return
        await self._wait_for_speaking_finished(
            min_counter=start_counter + 1,
            timeout_seconds=120.0,
        )
        if not self._closed:
            await self.send_state_command(_STATE_IDLE)

    async def _wait_for_speaking_finished(
        self,
        *,
        min_counter: int = 0,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = (loop.time() + timeout_seconds) if timeout_seconds else None
        while True:
            if self._speak_finished_counter >= min_counter:
                return
            if self._closed:
                raise WebSocketDisconnect()
            if deadline and loop.time() >= deadline:
                raise TimeoutError("Timed out waiting for speaking finished event")
            await asyncio.sleep(0.05)

    async def send_state_command(self, state_id: int) -> None:
        await self._send_state_command(state_id)

    async def reset_state(self) -> None:
        await self.send_state_command(_STATE_IDLE)

    async def start(self) -> None:
        if self._receiving_task is None:
            self._receiving_task = asyncio.create_task(self._receive_loop())

    async def close(self) -> None:
        self._closed = True
        if self._receiving_task:
            self._receiving_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._receiving_task

    async def start_talking(self, text: str) -> None:
        await self.speak(text)

    async def _start_talking_stream(self, text: str) -> None:
        self._speaking = True
        try:
            async with create_voicevox_client() as client:
                audio_query = await client.create_audio_query(text, speaker=29)
                wav_bytes = await audio_query.synthesis(speaker=29)

            pcm_bytes, tts_sample_rate, tts_channels, tts_sample_width = self._extract_pcm(wav_bytes)
            if len(pcm_bytes) == 0:
                self._speaking = False
                return

            if tts_sample_width != _SAMPLE_WIDTH:
                await self.ws.send_json({"error": f"unsupported sample width {tts_sample_width}"})
                self._speaking = False
                return

            bytes_per_second = tts_sample_rate * tts_channels * tts_sample_width
            segment_bytes = int(bytes_per_second * (_DOWN_SEGMENT_MILLIS / 1000))

            if segment_bytes <= 0:
                await self.ws.send_json({"error": "invalid segment size computed"})
                self._speaking = False
                return

            await self._send_segments(pcm_bytes, tts_sample_rate, tts_channels, segment_bytes)
        except Exception as exc:  # pragma: no cover
            self._speaking = False
            await self.ws.send_json({"error": f"voicevox synthesis failed: {exc}"})

    async def _receive_loop(self) -> None:
        try:
            while True:
                message = await self.ws.receive_bytes()
                if len(message) < _WS_HEADER_SIZE:
                    await self.ws.close(code=1003, reason="header too short")
                    break

                kind, msg_type, _reserved, _seq, payload_bytes = struct.unpack(
                    _WS_HEADER_FMT, message[:_WS_HEADER_SIZE]
                )

                payload = message[_WS_HEADER_SIZE:]
                if payload_bytes != len(payload):
                    await self.ws.close(code=1003, reason="payload length mismatch")
                    break

                if kind == _WS_KIND_PCM:
                    if msg_type == _WS_MSG_START:
                        self._handle_start()
                        continue

                    if msg_type == _WS_MSG_DATA:
                        if not self._handle_data(payload_bytes, payload):
                            break
                        continue

                    if msg_type == _WS_MSG_END:
                        await self._handle_end(payload_bytes, payload)
                        continue

                    await self.ws.close(code=1003, reason="unknown PCM msg type")
                    break

                if kind == _WS_KIND_WAKEWORD_EVT:
                    self._handle_wakeword_event(msg_type, payload)
                    continue

                if kind == _WS_KIND_STATE_EVT:
                    self._handle_state_event(msg_type, payload)
                    continue

                if kind == _WS_KIND_SPEAK_DONE_EVT:
                    self._handle_speak_done_event(msg_type, payload)
                    continue

                await self.ws.close(code=1003, reason="unsupported kind")
                break
        except WebSocketDisconnect:
            pass
        finally:
            self._closed = True
            self._speaking = False

    def _handle_start(self) -> None:
        logger.info("Received START")
        self._pcm_buffer = bytearray()
        self._streaming = True
        self._message_error = None

    def _handle_data(self, payload_bytes: int, payload: bytes) -> bool:
        logger.info("Received DATA payload_bytes=%d", payload_bytes)
        if not self._streaming:
            asyncio.create_task(self.ws.close(code=1003, reason="data received before start"))
            return False
        if payload_bytes % (_SAMPLE_WIDTH * _CHANNELS) != 0:
            asyncio.create_task(self.ws.close(code=1003, reason="invalid pcm chunk length"))
            return False
        self._pcm_buffer.extend(payload)
        if payload_bytes > 0:
            self._pcm_data_counter += 1
        return True

    async def _handle_end(self, payload_bytes: int, payload: bytes) -> None:
        logger.info("Received END payload_bytes=%d", payload_bytes)
        if not self._streaming:
            await self.ws.close(code=1003, reason="end received before start")
            return
        if payload_bytes % (_SAMPLE_WIDTH * _CHANNELS) != 0:
            await self.ws.close(code=1003, reason="invalid pcm tail length")
            return
        self._pcm_buffer.extend(payload)

        if len(self._pcm_buffer) == 0 or len(self._pcm_buffer) % (_SAMPLE_WIDTH * _CHANNELS) != 0:
            await self.ws.close(code=1003, reason="invalid accumulated pcm length")
            return

        # Uplink audio has been fully received: tell firmware to enter Thinking state.
        await self._send_state_command(_STATE_THINKING)

        frames = len(self._pcm_buffer) // (_SAMPLE_WIDTH * _CHANNELS)
        duration_seconds = frames / float(_SAMPLE_RATE_HZ)

        filepath, filename = self._save_wav(bytes(self._pcm_buffer))

        await self.ws.send_json(
            {
                "text": f"Saved as {filename}",
                "sample_rate": _SAMPLE_RATE_HZ,
                "frames": frames,
                "channels": _CHANNELS,
                "duration_seconds": round(duration_seconds, 3),
                "path": f"recordings/{filename}",
            }
        )

        transcript = await self._transcribe_async(bytes(self._pcm_buffer))

        self._streaming = False
        self._pcm_buffer = bytearray()

        if transcript.strip() == "":
            self._message_error = EmptyTranscriptError("Speech recognition result is empty")
            return

        self._transcript = transcript
        self._message_ready.set()

    def _handle_wakeword_event(self, msg_type: int, payload: bytes) -> None:
        if msg_type != _WS_MSG_DATA:
            return
        if len(payload) < 1:
            return
        logger.info("Received wakeword event")
        self._wakeword_event.set()

    def _handle_state_event(self, msg_type: int, payload: bytes) -> None:
        if msg_type != _WS_MSG_DATA:
            return
        if len(payload) < 1:
            return
        logger.info("Received firmware state=%d", int(payload[0]))

    def _handle_speak_done_event(self, msg_type: int, payload: bytes) -> None:
        if msg_type != _WS_MSG_DATA:
            return
        if len(payload) < 1:
            return
        self._speak_finished_counter += 1
        self._speaking = False
        logger.info("Received speak done event")

    async def _send_state_command(self, state_id: int) -> None:
        payload = struct.pack("<B", state_id)
        hdr = struct.pack(
            _WS_HEADER_FMT,
            _WS_KIND_STATE_CMD,
            _WS_MSG_DATA,
            0,
            self._down_seq,
            len(payload),
        )
        await self.ws.send_bytes(hdr + payload)
        self._down_seq += 1

    def _save_wav(self, pcm_bytes: bytes) -> tuple[Path, str]:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"rec_ws_{timestamp}.wav"
        filepath = self.recordings_dir / filename

        with wave.open(str(filepath), "wb") as wav_fp:
            wav_fp.setnchannels(_CHANNELS)
            wav_fp.setsampwidth(_SAMPLE_WIDTH)
            wav_fp.setframerate(_SAMPLE_RATE_HZ)
            wav_fp.writeframes(pcm_bytes)

        logger.info("Saved WAV: %s", filename)
        return filepath, filename

    async def _transcribe_async(self, pcm_bytes: bytes) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._transcribe(pcm_bytes))

    def _transcribe(self, pcm_bytes: bytes) -> str:
        audio = speech.RecognitionAudio(content=pcm_bytes)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=_SAMPLE_RATE_HZ,
            language_code="ja-JP",
        )
        response = self.speech_client.recognize(config=config, audio=audio)

        transcript = ""
        for result in response.results:
            logger.info("Transcript: %s", result.alternatives[0].transcript)
            transcript += result.alternatives[0].transcript
        return transcript

    def _extract_pcm(self, wav_bytes: bytes) -> tuple[bytes, int, int, int]:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            pcm_bytes = wf.readframes(wf.getnframes())
            tts_sample_rate = wf.getframerate()
            tts_channels = wf.getnchannels()
            tts_sample_width = wf.getsampwidth()
        return pcm_bytes, tts_sample_rate, tts_channels, tts_sample_width

    async def _send_segments(self, pcm_bytes: bytes, tts_sample_rate: int, tts_channels: int, segment_bytes: int) -> None:
        segments: list[bytes] = []
        offset = 0
        total = len(pcm_bytes)
        while offset < total:
            segments.append(pcm_bytes[offset : offset + segment_bytes])
            offset += segment_bytes

        loop = asyncio.get_running_loop()
        base_time = loop.time()

        for idx, segment in enumerate(segments):
            if idx == 0:
                target_ms = 0
            elif idx == 1:
                target_ms = _DOWN_SEGMENT_STAGGER_MILLIS
            else:
                target_ms = _DOWN_SEGMENT_STAGGER_MILLIS + (idx - 1) * _DOWN_SEGMENT_MILLIS

            target_time = base_time + target_ms / 1000
            now = loop.time()
            if target_time > now:
                await asyncio.sleep(target_time - now)

            await self._send_segment(segment, tts_sample_rate, tts_channels)

    async def _send_segment(self, segment_pcm: bytes, tts_sample_rate: int, tts_channels: int) -> None:
        logger.info("Sending segment bytes=%d", len(segment_pcm))
        start_payload = struct.pack("<IH", tts_sample_rate, tts_channels)
        start_hdr = struct.pack(
            _WS_HEADER_FMT,
            _WS_KIND_WAV,
            _WS_MSG_START,
            0,
            self._down_seq,
            len(start_payload),
        )
        await self.ws.send_bytes(start_hdr + start_payload)
        self._down_seq += 1

        seg_offset = 0
        seg_total = len(segment_pcm)
        while seg_offset < seg_total:
            chunk = segment_pcm[seg_offset : seg_offset + _DOWN_WAV_CHUNK]
            data_hdr = struct.pack(
                _WS_HEADER_FMT,
                _WS_KIND_WAV,
                _WS_MSG_DATA,
                0,
                self._down_seq,
                len(chunk),
            )
            await self.ws.send_bytes(data_hdr + chunk)
            self._down_seq += 1
            seg_offset += len(chunk)

        end_hdr = struct.pack(
            _WS_HEADER_FMT,
            _WS_KIND_WAV,
            _WS_MSG_END,
            0,
            self._down_seq,
            0,
        )
        await self.ws.send_bytes(end_hdr)
        self._down_seq += 1


__all__ = ["WsProxy", "TimeoutError", "EmptyTranscriptError", "create_voicevox_client"]
