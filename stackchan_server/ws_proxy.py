from __future__ import annotations

import asyncio
import os
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from logging import getLogger
from pathlib import Path
from typing import Any, Literal, Optional, Sequence, TypeAlias

from fastapi import WebSocket, WebSocketDisconnect
from google.protobuf.message import DecodeError

from . import __version__
from .generated_protobuf import websocket_message_pb2 as _ws_pb2
from .listen import EmptyTranscriptError, ListenHandler, TimeoutError
from .protobuf_ws import (
    encode_server_metadata_message,
    encode_servo_command_message,
    encode_state_command_message,
    parse_websocket_message,
)
from .server_wwd import ServerWwdController
from .speak import SpeakHandler
from .static import LISTEN_AUDIO_FORMAT
from .types import SpeechRecognizer, SpeechSynthesizer

logger = getLogger(__name__)

ws_pb2: Any = _ws_pb2

_BASE_DIR = Path(__file__).resolve().parent
_RECORDINGS_DIR = _BASE_DIR / "recordings"

_DOWN_WAV_CHUNK = 4096  # bytes per WebSocket frame for synthesized audio (raw PCM)
_DOWN_SEGMENT_MILLIS = (
    2000  # duration of a single START-DATA-END segment in milliseconds
)
_DOWN_SEGMENT_STAGGER_MILLIS = (
    _DOWN_SEGMENT_MILLIS // 2
)  # half interval for the second segment start
_LISTEN_AUDIO_TIMEOUT_SECONDS = 10.0
_DEBUG_RECORDING_ENABLED = os.getenv("DEBUG_RECODING") == "1"


class FirmwareState(IntEnum):
    IDLE = 0
    LISTENING = 1
    THINKING = 2
    SPEAKING = 3
    SERVER_WWD = 4


class ServoMoveType(StrEnum):
    MOVE_X = "move_x"
    MOVE_Y = "move_y"


class ServoWaitType(StrEnum):
    SLEEP = "sleep"


ServoMoveCommand: TypeAlias = tuple[
    Literal["move_x", "move_y"] | ServoMoveType, int, int
]
ServoSleepCommand: TypeAlias = tuple[Literal["sleep"] | ServoWaitType, int]
ServoCommand: TypeAlias = ServoMoveCommand | ServoSleepCommand


@dataclass(frozen=True)
class FirmwareMetadata:
    device_type: int
    display_width: int
    display_height: int
    has_device_wake_word: bool
    has_led: bool
    servo_type: int
    supports_audio_duplex: bool
    firmware_version: str


@dataclass(frozen=True)
class ServerMetadata:
    has_server_wake_word: bool
    server_version: str


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

        self.firmware_metadata: FirmwareMetadata | None = None
        self.server_metadata = ServerMetadata(
            has_server_wake_word=False,
            server_version=__version__,
        )

        self._down_seq = 0
        self._current_firmware_state: FirmwareState = FirmwareState.IDLE
        self._servo_done_counter = 0
        self._servo_sent_counter = 0
        self._pending_servo_wait_targets: deque[int] = deque()
        self._server_wwd = ServerWwdController(
            send_state_command=self.send_state_command,
            set_current_state=lambda state: setattr(
                self, "_current_firmware_state", FirmwareState(state)
            ),
            close_websocket=self.ws.close,
            current_state=lambda: int(self._current_firmware_state),
            is_closed=lambda: self._closed,
            on_detected=self._wakeword_event.set,
            server_wwd_state=int(FirmwareState.SERVER_WWD),
            idle_state=int(FirmwareState.IDLE),
        )

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def current_state(self) -> FirmwareState:
        return self._current_firmware_state

    @property
    def receive_task(self) -> Optional[asyncio.Task]:
        return self._receiving_task

    @property
    def has_server_wakeword_detector(self) -> bool:
        return self._server_wwd.available

    def trigger_wakeword(self) -> None:
        """Web API から擬似的に WAKEWORD_EVT を発火させる。"""
        logger.info("Triggered wakeword via API")
        self._wakeword_event.set()

    async def wait_for_talk_session(self) -> None:
        while True:
            if self._wakeword_event.is_set():
                await self._server_wwd.stop()
                self._wakeword_event.clear()
                return
            if self._closed:
                raise WebSocketDisconnect()
            await asyncio.sleep(0.05)

    async def listen(self) -> str:
        await self._server_wwd.stop()
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

    async def send_state_command(
        self,
        state_id: int | FirmwareState,
    ) -> None:
        await self._send_state_command(state_id)

    async def reset_state(self) -> None:
        await self.send_state_command(FirmwareState.IDLE)
        self._current_firmware_state = FirmwareState.IDLE
        self._server_wwd.schedule_restart()

    async def move_servo(self, commands: Sequence[ServoCommand]) -> None:
        previous_counter = self._servo_sent_counter
        target_counter = previous_counter + 1
        self._servo_sent_counter = target_counter
        self._pending_servo_wait_targets.append(target_counter)
        try:
            await self._send_ws_bytes(
                encode_servo_command_message(self._next_down_seq(), commands)
            )
        except Exception:
            if (
                self._pending_servo_wait_targets
                and self._pending_servo_wait_targets[-1] == target_counter
            ):
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
        await self._server_wwd.stop()
        if self._receiving_task:
            self._receiving_task.cancel()
            with suppress(asyncio.CancelledError):
                try:
                    await self._receiving_task
                except RuntimeError as exc:
                    if not self._is_closed_websocket_runtime_error(exc):
                        raise
        await self._listener.close()

    async def start_talking(self, text: str) -> None:
        await self.speak(text)

    async def enable_auto_server_wakeword_detection(self) -> None:
        await self._server_wwd.enable_auto_detection()
        if self.firmware_metadata is not None:
            await self._server_wwd.start_if_available()

    async def _receive_loop(self) -> None:
        try:
            while True:
                try:
                    raw_message = await self.ws.receive_bytes()
                except RuntimeError as exc:
                    if self._is_closed_websocket_runtime_error(exc):
                        break
                    raise
                try:
                    message = parse_websocket_message(raw_message)
                except DecodeError:
                    await self.ws.close(code=1003, reason="invalid protobuf message")
                    break

                if message.kind == ws_pb2.MESSAGE_KIND_SERVER_WWD_PCM:
                    if not await self._server_wwd.handle_pcm_message(message, ws_pb2=ws_pb2):
                        break
                    continue

                if message.kind == ws_pb2.MESSAGE_KIND_AUDIO_PCM:
                    if not await self._handle_audio_pcm_message(message):
                        break
                    continue

                if message.kind == ws_pb2.MESSAGE_KIND_WAKE_WORD_EVT:
                    self._handle_wakeword_event(message)
                    continue

                if message.kind == ws_pb2.MESSAGE_KIND_FIRMWARE_METADATA:
                    await self._handle_firmware_metadata(message)
                    continue

                if message.kind == ws_pb2.MESSAGE_KIND_STATE_EVT:
                    self._handle_state_event(message)
                    continue

                if message.kind == ws_pb2.MESSAGE_KIND_SPEAK_DONE_EVT:
                    self._handle_speak_done_event(message)
                    continue

                if message.kind == ws_pb2.MESSAGE_KIND_SERVO_DONE_EVT:
                    self._handle_servo_done_event(message)
                    continue

                await self.ws.close(code=1003, reason="unsupported kind")
                break
        except WebSocketDisconnect:
            pass
        finally:
            self._closed = True

    async def _handle_audio_pcm_message(self, message: Any) -> bool:
        body_name = message.WhichOneof("body")

        if (
            message.message_type == ws_pb2.MESSAGE_TYPE_START
            and body_name == "audio_pcm_start"
        ):
            return await self._listener.handle_start(self.ws)

        if (
            message.message_type == ws_pb2.MESSAGE_TYPE_DATA
            and body_name == "audio_pcm_data"
        ):
            payload = bytes(message.audio_pcm_data.pcm_bytes)
            return await self._listener.handle_data(self.ws, len(payload), payload)

        if (
            message.message_type == ws_pb2.MESSAGE_TYPE_END
            and body_name == "audio_pcm_end"
        ):
            await self._listener.handle_end(
                self.ws,
                payload_bytes=0,
                payload=b"",
                send_state_command=self.send_state_command,
                thinking_state=FirmwareState.THINKING,
            )
            return True

        await self.ws.close(code=1003, reason="unknown PCM protobuf body")
        return False

    def _handle_wakeword_event(self, message: Any) -> None:
        if message.message_type != ws_pb2.MESSAGE_TYPE_DATA:
            return
        if message.WhichOneof("body") != "wake_word_evt":
            return
        if not message.wake_word_evt.detected:
            return
        logger.info("Received wakeword event")
        self._wakeword_event.set()

    async def _handle_firmware_metadata(self, message: Any) -> None:
        if message.message_type != ws_pb2.MESSAGE_TYPE_DATA:
            return
        if message.WhichOneof("body") != "firmware_metadata":
            return

        metadata = message.firmware_metadata
        self.firmware_metadata = FirmwareMetadata(
            device_type=int(metadata.device_type),
            display_width=int(metadata.display_width),
            display_height=int(metadata.display_height),
            has_device_wake_word=bool(metadata.has_device_wake_word),
            has_led=bool(metadata.has_led),
            servo_type=int(metadata.servo_type),
            supports_audio_duplex=bool(metadata.supports_audio_duplex),
            firmware_version=metadata.firmware_version,
        )
        logger.info(
            "Received firmware metadata device_type=%d display=%dx%d wakeword=%s led=%s servo_type=%d duplex=%s version=%s",
            self.firmware_metadata.device_type,
            self.firmware_metadata.display_width,
            self.firmware_metadata.display_height,
            self.firmware_metadata.has_device_wake_word,
            self.firmware_metadata.has_led,
            self.firmware_metadata.servo_type,
            self.firmware_metadata.supports_audio_duplex,
            self.firmware_metadata.firmware_version,
        )
        self.server_metadata = self._build_server_metadata(self.firmware_metadata)
        await self._send_ws_bytes(
            encode_server_metadata_message(
                self._next_down_seq(),
                has_server_wake_word=self.server_metadata.has_server_wake_word,
                server_version=self.server_metadata.server_version,
            )
        )
        if self._server_wwd.auto_start_enabled:
            await self._server_wwd.start_if_available()

    def _build_server_metadata(
        self, firmware_metadata: FirmwareMetadata
    ) -> ServerMetadata:
        should_use_server_wake_word = self._server_wwd.available
        return ServerMetadata(
            has_server_wake_word=should_use_server_wake_word,
            server_version=__version__,
        )

    def _handle_state_event(self, message: Any) -> None:
        if message.message_type != ws_pb2.MESSAGE_TYPE_DATA:
            return
        if message.WhichOneof("body") != "state_evt":
            return
        raw_state = int(message.state_evt.state)
        try:
            state = FirmwareState(raw_state)
            self._current_firmware_state = state
            logger.info("Received firmware state=%s(%d)", state.name, raw_state)
        except ValueError:
            logger.info("Received firmware state=%d", raw_state)

    def _handle_speak_done_event(self, message: Any) -> None:
        if message.message_type != ws_pb2.MESSAGE_TYPE_DATA:
            return
        if message.WhichOneof("body") != "speak_done_evt":
            return
        if not message.speak_done_evt.done:
            return
        self._speaker.handle_speak_done_event()

    def _handle_servo_done_event(self, message: Any) -> None:
        if message.message_type != ws_pb2.MESSAGE_TYPE_DATA:
            return
        if message.WhichOneof("body") != "servo_done_evt":
            return
        if not message.servo_done_evt.done:
            return
        self._servo_done_counter += 1
        logger.info("Received servo done event")

    async def _send_state_command(
        self,
        state_id: int | FirmwareState,
    ) -> None:
        await self._send_ws_bytes(
            encode_state_command_message(
                self._next_down_seq(),
                int(state_id),
            )
        )

    async def _send_ws_bytes(self, data: bytes) -> None:
        try:
            await self.ws.send_bytes(data)
        except RuntimeError as exc:
            self._raise_websocket_disconnect_from_runtime_error(exc)

    def _is_closed_websocket_runtime_error(self, exc: RuntimeError) -> bool:
        message = str(exc)
        return (
            'Cannot call "send" once a close message has been sent.' in message
            or 'WebSocket is not connected. Need to call "accept" first.' in message
        )

    def _raise_websocket_disconnect_from_runtime_error(self, exc: RuntimeError) -> None:
        if not self._is_closed_websocket_runtime_error(exc):
            raise exc
        self._closed = True
        raise WebSocketDisconnect() from exc

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
    "FirmwareMetadata",
    "FirmwareState",
    "ServerMetadata",
    "TimeoutError",
    "EmptyTranscriptError",
    "ServoCommand",
    "ServoMoveType",
    "ServoWaitType",
]
