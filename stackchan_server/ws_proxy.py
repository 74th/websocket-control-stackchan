from __future__ import annotations

import asyncio
import os
import struct
from collections import deque
from contextlib import suppress
from enum import IntEnum
from logging import getLogger
from pathlib import Path
from typing import Literal, Optional, Sequence, TypeAlias

from fastapi import WebSocket, WebSocketDisconnect

from .listen import EmptyTranscriptError, ListenHandler, TimeoutError
from .speak import SpeakHandler
from .static import LISTEN_AUDIO_FORMAT
from .types import SpeechRecognizer, SpeechSynthesizer

logger = getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent
_RECORDINGS_DIR = _BASE_DIR / "recordings"

_WS_HEADER_FMT = "<BBBHH"  # kind, msg_type, reserved, seq, payload_bytes
_WS_HEADER_SIZE = struct.calcsize(_WS_HEADER_FMT)

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
    SERVO_CMD = 7
    SERVO_DONE_EVT = 8


class _WsMsgType(IntEnum):
    START = 1
    DATA = 2
    END = 3


class _ServoOp(IntEnum):
    SLEEP = 0
    MOVE_X = 1
    MOVE_Y = 2


ServoMoveCommand: TypeAlias = tuple[Literal["move_x", "move_y"], int, int]
ServoSleepCommand: TypeAlias = tuple[Literal["sleep"], int]
ServoCommand: TypeAlias = ServoMoveCommand | ServoSleepCommand


def _ensure_range(value: int, *, minimum: int, maximum: int, label: str) -> int:
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}: {value}")
    return value


def _encode_servo_commands(commands: Sequence[ServoCommand]) -> bytes:
    normalized = list(commands)
    _ensure_range(len(normalized), minimum=0, maximum=255, label="servo command count")

    payload = bytearray()
    payload.append(len(normalized))

    for index, command in enumerate(normalized):
        name = command[0]
        if name == "sleep":
            if len(command) != 2:
                raise ValueError(f"sleep command at index {index} must be ('sleep', duration_ms)")
            duration_ms = _ensure_range(int(command[1]), minimum=-32768, maximum=32767, label="sleep duration")
            payload.append(_ServoOp.SLEEP)
            payload.extend(struct.pack("<h", duration_ms))
            continue

        if name in ("move_x", "move_y"):
            if len(command) != 3:
                raise ValueError(
                    f"{name} command at index {index} must be ('{name}', angle, duration_ms)"
                )
            angle = _ensure_range(int(command[1]), minimum=-128, maximum=127, label="servo angle")
            duration_ms = _ensure_range(int(command[2]), minimum=-32768, maximum=32767, label="servo duration")
            payload.append(_ServoOp.MOVE_X if name == "move_x" else _ServoOp.MOVE_Y)
            payload.extend(struct.pack("<bh", angle, duration_ms))
            continue

        raise ValueError(f"unsupported servo command at index {index}: {name}")

    return bytes(payload)

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
            sample_width=LISTEN_AUDIO_FORMAT.sample_width,
            speech_synthesizer=self.speech_synthesizer,
            recordings_dir=self.recordings_dir,
            debug_recording=self._debug_recording,
        )

        self._receiving_task: Optional[asyncio.Task] = None
        self._closed = False

        self._down_seq = 0
        self._current_firmware_state: FirmwareState = FirmwareState.IDLE
        self._servo_done_counter = 0
        self._servo_sent_counter = 0
        self._pending_servo_wait_targets: deque[int] = deque()

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

    async def move_servo(self, commands: Sequence[ServoCommand]) -> None:
        payload = _encode_servo_commands(commands)
        previous_counter = self._servo_sent_counter
        target_counter = previous_counter + 1
        self._servo_sent_counter = target_counter
        self._pending_servo_wait_targets.append(target_counter)
        try:
            await self._send_packet(_WsKind.SERVO_CMD, _WsMsgType.DATA, payload)
        except Exception:
            if self._pending_servo_wait_targets and self._pending_servo_wait_targets[-1] == target_counter:
                self._pending_servo_wait_targets.pop()
            self._servo_sent_counter = previous_counter
            raise

    async def wait_servo_complete(self, timeout_seconds: float | None = 120.0) -> None:
        target_counter = (
            self._pending_servo_wait_targets.popleft()
            if self._pending_servo_wait_targets
            else self._servo_done_counter + 1
        )
        await self._wait_for_counter(
            current=lambda: self._servo_done_counter,
            min_counter=target_counter,
            timeout_seconds=timeout_seconds,
            is_closed=lambda: self._closed,
            label="servo completed event",
        )

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

                if kind == _WsKind.SERVO_DONE_EVT:
                    self._handle_servo_done_event(msg_type, payload)
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

    def _handle_servo_done_event(self, msg_type: int, payload: bytes) -> None:
        if msg_type != _WsMsgType.DATA:
            return
        if len(payload) < 1:
            return
        self._servo_done_counter += 1
        logger.info("Received servo done event")

    async def _send_state_command(self, state_id: int | FirmwareState) -> None:
        payload = struct.pack("<B", int(state_id))
        await self._send_packet(_WsKind.STATE_CMD, _WsMsgType.DATA, payload)

    async def _send_packet(self, kind: _WsKind, msg_type: _WsMsgType, payload: bytes = b"") -> None:
        hdr = struct.pack(
            _WS_HEADER_FMT,
            int(kind),
            int(msg_type),
            0,
            self._down_seq,
            len(payload),
        )
        await self.ws.send_bytes(hdr + payload)
        self._down_seq += 1

    async def _wait_for_counter(
        self,
        *,
        current,
        min_counter: int,
        timeout_seconds: float | None,
        is_closed,
        label: str,
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = (loop.time() + timeout_seconds) if timeout_seconds else None
        while True:
            if current() >= min_counter:
                return
            if is_closed():
                raise WebSocketDisconnect()
            if deadline and loop.time() >= deadline:
                raise TimeoutError(f"Timed out waiting for {label}")
            await asyncio.sleep(0.05)

    def _next_down_seq(self) -> int:
        seq = self._down_seq
        self._down_seq += 1
        return seq


__all__ = [
    "WsProxy",
    "FirmwareState",
    "TimeoutError",
    "EmptyTranscriptError",
    "ServoCommand",
]
