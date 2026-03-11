from __future__ import annotations

import asyncio
import os
import struct
from contextlib import suppress
from enum import IntEnum
from logging import getLogger
from pathlib import Path
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from .listen import EmptyTranscriptError, ListenHandler, TimeoutError
from .speak import SpeakHandler
from .types import SpeechRecognizer, SpeechSynthesizer

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

class WsProxy:
    def __init__(
        self,
        websocket: WebSocket,
        speech_recognizer: SpeechRecognizer,
        speech_synthesizer: SpeechSynthesizer,
    ):
        self.ws = websocket
        self.speech_recognizer = speech_recognizer
        self.speech_synthesizer = speech_synthesizer
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
        self._speaker = SpeakHandler(
            websocket=self.ws,
            ws_header_fmt=_WS_HEADER_FMT,
            wav_kind=_WsKind.WAV.value,
            start_msg_type=_WsMsgType.START.value,
            data_msg_type=_WsMsgType.DATA.value,
            end_msg_type=_WsMsgType.END.value,
            down_wav_chunk=_DOWN_WAV_CHUNK,
            down_segment_millis=_DOWN_SEGMENT_MILLIS,
            down_segment_stagger_millis=_DOWN_SEGMENT_STAGGER_MILLIS,
            sample_width=_SAMPLE_WIDTH,
            speech_synthesizer=self.speech_synthesizer,
            recordings_dir=self.recordings_dir,
            debug_recording=self._debug_recording,
        )

        self._receiving_task: Optional[asyncio.Task] = None
        self._closed = False

        self._down_seq = 0
        self._current_firmware_state: FirmwareState = FirmwareState.IDLE

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def current_state(self) -> FirmwareState:
        return self._current_firmware_state

    @property
    def receive_task(self) -> Optional[asyncio.Task]:
        return self._receiving_task

    def trigger_wakeword(self) -> None:
        """Web API から擬似的に WAKEWORD_EVT を発火させる。"""
        logger.info("Triggered wakeword via API")
        self._wakeword_event.set()

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
        await self._speaker.speak(
            text,
            next_seq=self._next_down_seq,
            send_state_command=self.send_state_command,
            idle_state=FirmwareState.IDLE,
            is_closed=lambda: self._closed,
        )

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
            self._current_firmware_state = state
            logger.info("Received firmware state=%s(%d)", state.name, raw_state)
        except ValueError:
            logger.info("Received firmware state=%d", raw_state)

    def _handle_speak_done_event(self, msg_type: int, payload: bytes) -> None:
        if msg_type != _WsMsgType.DATA:
            return
        if len(payload) < 1:
            return
        self._speaker.handle_speak_done_event()

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

    def _next_down_seq(self) -> int:
        seq = self._down_seq
        self._down_seq += 1
        return seq


__all__ = ["WsProxy", "FirmwareState", "TimeoutError", "EmptyTranscriptError"]
