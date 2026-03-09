from __future__ import annotations

import asyncio
import io
import os
import struct
import wave
from contextlib import suppress
from enum import IntEnum
from logging import getLogger
from pathlib import Path
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from vvclient import Client as VVClient

from .listen import EmptyTranscriptError, ListenHandler, TimeoutError
from .types import SpeechRecognizer

logger = getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent
_RECORDINGS_DIR = _BASE_DIR / "recordings"

_WS_HEADER_FMT = "<BBBHH"  # kind, msg_type, reserved, seq, payload_bytes
_WS_HEADER_SIZE = struct.calcsize(_WS_HEADER_FMT)

_SAMPLE_RATE_HZ = 16000
_CHANNELS = 1
_SAMPLE_WIDTH = 2  # bytes

_DOWN_WAV_CHUNK = 4096  # bytes per WebSocket frame for synthesized audio (raw PCM)
_DOWN_SEGMENT_MILLIS = 2000  # duration of a single START-DATA-END segment in milliseconds
_DOWN_SEGMENT_STAGGER_MILLIS = _DOWN_SEGMENT_MILLIS // 2  # half interval for the second segment start
_LISTEN_AUDIO_TIMEOUT_SECONDS = 10.0
_DEBUG_RECORDING_ENABLED = os.getenv("DEBUG_RECODING") == "1"


class FirmwareState(IntEnum):
    IDLE = 0
    LISTENING = 1
    THINKING = 2
    SPEAKING = 3


class _WsKind(IntEnum):
    PCM = 1
    WAV = 2
    STATE_CMD = 3
    WAKEWORD_EVT = 4
    STATE_EVT = 5
    SPEAK_DONE_EVT = 6


class _WsMsgType(IntEnum):
    START = 1
    DATA = 2
    END = 3


def create_voicevox_client() -> VVClient:
    voicevox_url = os.getenv("STACKCHAN_VOICEVOX_URL", "http://localhost:50021")
    return VVClient(base_uri=voicevox_url)


class WsProxy:
    def __init__(self, websocket: WebSocket, speech_recognizer: SpeechRecognizer):
        self.ws = websocket
        self.speech_recognizer = speech_recognizer
        self.recordings_dir = _RECORDINGS_DIR
        self._debug_recording = _DEBUG_RECORDING_ENABLED
        if self._debug_recording:
            _RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
            self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self._wakeword_event = asyncio.Event()
        self._listener = ListenHandler(
            speech_recognizer=self.speech_recognizer,
            recordings_dir=self.recordings_dir,
            debug_recording=self._debug_recording,
            sample_rate_hz=_SAMPLE_RATE_HZ,
            channels=_CHANNELS,
            sample_width=_SAMPLE_WIDTH,
            listen_audio_timeout_seconds=_LISTEN_AUDIO_TIMEOUT_SECONDS,
        )

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
        return await self._listener.listen(
            send_state_command=self.send_state_command,
            is_closed=lambda: self._closed,
            idle_state=FirmwareState.IDLE,
            listening_state=FirmwareState.LISTENING,
        )

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
            await self.send_state_command(FirmwareState.IDLE)

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

    async def send_state_command(self, state_id: int | FirmwareState) -> None:
        await self._send_state_command(state_id)

    async def reset_state(self) -> None:
        await self.send_state_command(FirmwareState.IDLE)

    async def start(self) -> None:
        if self._receiving_task is None:
            self._receiving_task = asyncio.create_task(self._receive_loop())

    async def close(self) -> None:
        self._closed = True
        if self._receiving_task:
            self._receiving_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._receiving_task
        await self._listener.close()

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

                if kind == _WsKind.PCM:
                    if msg_type == _WsMsgType.START:
                        if not await self._listener.handle_start(self.ws):
                            break
                        continue

                    if msg_type == _WsMsgType.DATA:
                        if not await self._listener.handle_data(self.ws, payload_bytes, payload):
                            break
                        continue

                    if msg_type == _WsMsgType.END:
                        await self._listener.handle_end(
                            self.ws,
                            payload_bytes=payload_bytes,
                            payload=payload,
                            send_state_command=self.send_state_command,
                            thinking_state=FirmwareState.THINKING,
                        )
                        continue

                    await self.ws.close(code=1003, reason="unknown PCM msg type")
                    break

                if kind == _WsKind.WAKEWORD_EVT:
                    self._handle_wakeword_event(msg_type, payload)
                    continue

                if kind == _WsKind.STATE_EVT:
                    self._handle_state_event(msg_type, payload)
                    continue

                if kind == _WsKind.SPEAK_DONE_EVT:
                    self._handle_speak_done_event(msg_type, payload)
                    continue

                await self.ws.close(code=1003, reason="unsupported kind")
                break
        except WebSocketDisconnect:
            pass
        finally:
            self._closed = True
            self._speaking = False

    def _handle_wakeword_event(self, msg_type: int, payload: bytes) -> None:
        if msg_type != _WsMsgType.DATA:
            return
        if len(payload) < 1:
            return
        logger.info("Received wakeword event")
        self._wakeword_event.set()

    def _handle_state_event(self, msg_type: int, payload: bytes) -> None:
        if msg_type != _WsMsgType.DATA:
            return
        if len(payload) < 1:
            return
        raw_state = int(payload[0])
        try:
            state = FirmwareState(raw_state)
            logger.info("Received firmware state=%s(%d)", state.name, raw_state)
        except ValueError:
            logger.info("Received firmware state=%d", raw_state)

    def _handle_speak_done_event(self, msg_type: int, payload: bytes) -> None:
        if msg_type != _WsMsgType.DATA:
            return
        if len(payload) < 1:
            return
        self._speak_finished_counter += 1
        self._speaking = False
        logger.info("Received speak done event")

    async def _send_state_command(self, state_id: int | FirmwareState) -> None:
        payload = struct.pack("<B", int(state_id))
        hdr = struct.pack(
            _WS_HEADER_FMT,
            _WsKind.STATE_CMD.value,
            _WsMsgType.DATA.value,
            0,
            self._down_seq,
            len(payload),
        )
        await self.ws.send_bytes(hdr + payload)
        self._down_seq += 1

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
            _WsKind.WAV.value,
            _WsMsgType.START.value,
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
                _WsKind.WAV.value,
                _WsMsgType.DATA.value,
                0,
                self._down_seq,
                len(chunk),
            )
            await self.ws.send_bytes(data_hdr + chunk)
            self._down_seq += 1
            seg_offset += len(chunk)

        end_hdr = struct.pack(
            _WS_HEADER_FMT,
            _WsKind.WAV.value,
            _WsMsgType.END.value,
            0,
            self._down_seq,
            0,
        )
        await self.ws.send_bytes(end_hdr)
        self._down_seq += 1


__all__ = ["WsProxy", "FirmwareState", "TimeoutError", "EmptyTranscriptError", "create_voicevox_client"]
