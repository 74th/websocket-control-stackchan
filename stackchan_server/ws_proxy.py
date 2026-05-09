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
    ListeningPurpose,
    encode_server_metadata_message,
    encode_servo_command_message,
    encode_state_command_message,
    parse_websocket_message,
)
from .speak import SpeakHandler
from .static import LISTEN_AUDIO_FORMAT
from .types import SpeechRecognizer, SpeechSynthesizer
from .wakeup_word_detection import (
    WakeWordDetectionError,
    create_server_side_wake_word_detector,
)

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
_SERVER_WAKEWORD_RESTART_DELAY_SECONDS = 0.25
_TRAILING_PCM_DRAIN_SECONDS = 1.0


class FirmwareState(IntEnum):
    IDLE = 0
    LISTENING = 1
    THINKING = 2
    SPEAKING = 3


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
        self._server_wakeword_detector = create_server_side_wake_word_detector()
        self._server_wakeword_task: Optional[asyncio.Task[bool]] = None
        self._server_wakeword_restart_task: Optional[asyncio.Task[None]] = None
        self._auto_start_server_wakeword = False
        self._drain_trailing_pcm_until_end = False
        self._drain_trailing_pcm_deadline: float | None = None

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
        return self._server_wakeword_detector is not None

    def trigger_wakeword(self) -> None:
        """Web API から擬似的に WAKEWORD_EVT を発火させる。"""
        logger.info("Triggered wakeword via API")
        self._wakeword_event.set()

    async def wait_for_talk_session(self) -> None:
        while True:
            if self._wakeword_event.is_set():
                await self.stop_server_wakeword_detection()
                self._wakeword_event.clear()
                return
            if self._closed:
                raise WebSocketDisconnect()
            await asyncio.sleep(0.05)

    async def listen(self) -> str:
        await self.stop_server_wakeword_detection()
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
        *,
        listening_purpose: ListeningPurpose = ListeningPurpose.SPEECH,
    ) -> None:
        await self._send_state_command(
            state_id,
            listening_purpose=listening_purpose,
        )

    async def reset_state(self) -> None:
        await self.send_state_command(FirmwareState.IDLE)
        self._current_firmware_state = FirmwareState.IDLE
        self._schedule_server_wakeword_restart()

    async def move_servo(self, commands: Sequence[ServoCommand]) -> None:
        previous_counter = self._servo_sent_counter
        target_counter = previous_counter + 1
        self._servo_sent_counter = target_counter
        self._pending_servo_wait_targets.append(target_counter)
        try:
            await self.ws.send_bytes(
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
        self._cancel_server_wakeword_restart_task()
        await self.stop_server_wakeword_detection()
        if self._receiving_task:
            self._receiving_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._receiving_task
        await self._listener.close()

    async def start_talking(self, text: str) -> None:
        await self.speak(text)

    async def enable_auto_server_wakeword_detection(self) -> None:
        self._auto_start_server_wakeword = True
        await self.start_server_wakeword_detection_if_available()

    async def start_server_wakeword_detection_if_available(self) -> bool:
        if (
            self._closed
            or self._server_wakeword_detector is None
            or not self.server_metadata.has_server_wake_word
            or self.current_state != FirmwareState.IDLE
        ):
            return False

        if self._server_wakeword_task is not None and not self._server_wakeword_task.done():
            return True

        self._cancel_server_wakeword_restart_task()
        self._server_wakeword_task = asyncio.create_task(
            self._run_server_wakeword_detection(),
            name="server-side-wakeword-detection",
        )
        return True

    async def stop_server_wakeword_detection(self) -> None:
        self._cancel_server_wakeword_restart_task()
        task = self._server_wakeword_task
        if task is None:
            return

        if task.done():
            self._server_wakeword_task = None
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Server-side wake-word detection task failed")
            return

        task.cancel()
        self._server_wakeword_task = None
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Server-side wake-word detection task failed")

    async def request_server_wakeword_detection(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> bool:
        if self._server_wakeword_detector is None or not self.server_metadata.has_server_wake_word:
            raise WakeWordDetectionError(
                "Server-side wake-word detection is not available for this connection"
            )
        if self._closed:
            raise WebSocketDisconnect()

        started = await self.start_server_wakeword_detection_if_available()
        if not started:
            raise WakeWordDetectionError(
                "Server-side wake-word detection could not be started in the current state"
            )

        task = self._server_wakeword_task
        if task is None:
            raise WakeWordDetectionError("Server-side wake-word detection task is unavailable")

        try:
            if timeout_seconds is None:
                return await asyncio.shield(task)
            return await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            await self.stop_server_wakeword_detection()
            raise WakeWordDetectionError("Server-side wake-word detection timed out") from exc

    async def _receive_loop(self) -> None:
        try:
            while True:
                raw_message = await self.ws.receive_bytes()
                try:
                    message = parse_websocket_message(raw_message)
                except DecodeError:
                    await self.ws.close(code=1003, reason="invalid protobuf message")
                    break

                if message.kind == ws_pb2.MESSAGE_KIND_AUDIO_PCM:
                    body_name = message.WhichOneof("body")

                    if self._should_drain_trailing_pcm():
                        if (
                            message.message_type == ws_pb2.MESSAGE_TYPE_START
                            and body_name == "audio_pcm_start"
                        ):
                            logger.info(
                                "Received a new PCM START while draining trailing wake-word audio; resuming normal routing"
                            )
                            self._clear_trailing_pcm_drain()
                        elif (
                            message.message_type == ws_pb2.MESSAGE_TYPE_DATA
                            and body_name == "audio_pcm_data"
                        ):
                            logger.info(
                                "Discarding trailing PCM DATA after wake-word detection stop payload_bytes=%d",
                                len(message.audio_pcm_data.pcm_bytes),
                            )
                            continue
                        elif (
                            message.message_type == ws_pb2.MESSAGE_TYPE_END
                            and body_name == "audio_pcm_end"
                        ):
                            logger.info(
                                "Finished draining trailing PCM after wake-word detection stop"
                            )
                            self._clear_trailing_pcm_drain()
                            continue

                    if (
                        self._server_wakeword_detector is not None
                        and self._server_wakeword_detector.running
                    ):
                        if (
                            message.message_type == ws_pb2.MESSAGE_TYPE_START
                            and body_name == "audio_pcm_start"
                        ):
                            await self._server_wakeword_detector.handle_start()
                            continue

                        if (
                            message.message_type == ws_pb2.MESSAGE_TYPE_DATA
                            and body_name == "audio_pcm_data"
                        ):
                            payload = bytes(message.audio_pcm_data.pcm_bytes)
                            await self._server_wakeword_detector.handle_data(payload)
                            continue

                        if (
                            message.message_type == ws_pb2.MESSAGE_TYPE_END
                            and body_name == "audio_pcm_end"
                        ):
                            await self._server_wakeword_detector.handle_end()
                            continue

                        await self.ws.close(code=1003, reason="unknown wakeword PCM protobuf body")
                        break

                    if (
                        message.message_type == ws_pb2.MESSAGE_TYPE_START
                        and body_name == "audio_pcm_start"
                    ):
                        if not await self._listener.handle_start(self.ws):
                            break
                        continue

                    if (
                        message.message_type == ws_pb2.MESSAGE_TYPE_DATA
                        and body_name == "audio_pcm_data"
                    ):
                        payload = bytes(message.audio_pcm_data.pcm_bytes)
                        if not await self._listener.handle_data(
                            self.ws, len(payload), payload
                        ):
                            break
                        continue

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
                        continue

                    await self.ws.close(code=1003, reason="unknown PCM protobuf body")
                    break

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
        await self.ws.send_bytes(
            encode_server_metadata_message(
                self._next_down_seq(),
                has_server_wake_word=self.server_metadata.has_server_wake_word,
                server_version=self.server_metadata.server_version,
            )
        )
        if self._auto_start_server_wakeword:
            await self.start_server_wakeword_detection_if_available()

    def _build_server_metadata(
        self, firmware_metadata: FirmwareMetadata
    ) -> ServerMetadata:
        should_use_server_wake_word = self._server_wakeword_detector is not None
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
        *,
        listening_purpose: ListeningPurpose = ListeningPurpose.SPEECH,
    ) -> None:
        await self.ws.send_bytes(
            encode_state_command_message(
                self._next_down_seq(),
                int(state_id),
                listening_purpose=int(listening_purpose),
            )
        )

    async def _run_server_wakeword_detection(self) -> bool:
        detector = self._server_wakeword_detector
        if detector is None:
            return False

        detected = False
        should_restart = False
        try:
            await detector.start()
            await self.send_state_command(
                FirmwareState.LISTENING,
                listening_purpose=ListeningPurpose.WAKE_WORD,
            )
            detected = await detector.wait_result()
            if detected:
                self._wakeword_event.set()
            return detected
        except asyncio.CancelledError:
            raise
        except WakeWordDetectionError as exc:
            logger.warning("Server-side wake-word detection stopped: %s", exc)
            return False
        except Exception:
            logger.exception("Server-side wake-word detection failed")
            return False
        finally:
            await detector.stop()
            self._arm_trailing_pcm_drain()
            if not self._closed:
                self._current_firmware_state = FirmwareState.IDLE
                try:
                    await self.send_state_command(FirmwareState.IDLE)
                except Exception:
                    logger.exception("Failed to return firmware to idle after wake-word detection")
            should_restart = (
                self._auto_start_server_wakeword
                and not detected
                and not self._wakeword_event.is_set()
                and not self._closed
            )
            if self._server_wakeword_task is asyncio.current_task():
                self._server_wakeword_task = None
            if should_restart:
                self._schedule_server_wakeword_restart()

    def _schedule_server_wakeword_restart(
        self,
        delay_seconds: float = _SERVER_WAKEWORD_RESTART_DELAY_SECONDS,
    ) -> None:
        if not self._auto_start_server_wakeword or self._closed:
            return

        self._cancel_server_wakeword_restart_task()
        self._server_wakeword_restart_task = asyncio.create_task(
            self._restart_server_wakeword_detection_after_delay(delay_seconds),
            name="server-side-wakeword-restart",
        )

    def _cancel_server_wakeword_restart_task(self) -> None:
        task = self._server_wakeword_restart_task
        if task is None:
            return
        self._server_wakeword_restart_task = None
        task.cancel()

    async def _restart_server_wakeword_detection_after_delay(
        self,
        delay_seconds: float,
    ) -> None:
        try:
            await asyncio.sleep(delay_seconds)
            if self._closed:
                return
            await self.start_server_wakeword_detection_if_available()
        except asyncio.CancelledError:
            raise
        finally:
            if self._server_wakeword_restart_task is asyncio.current_task():
                self._server_wakeword_restart_task = None

    def _arm_trailing_pcm_drain(
        self,
        timeout_seconds: float = _TRAILING_PCM_DRAIN_SECONDS,
    ) -> None:
        loop = asyncio.get_running_loop()
        self._drain_trailing_pcm_until_end = True
        self._drain_trailing_pcm_deadline = loop.time() + timeout_seconds

    def _clear_trailing_pcm_drain(self) -> None:
        self._drain_trailing_pcm_until_end = False
        self._drain_trailing_pcm_deadline = None

    def _should_drain_trailing_pcm(self) -> bool:
        if not self._drain_trailing_pcm_until_end:
            return False
        deadline = self._drain_trailing_pcm_deadline
        if deadline is None:
            return True
        if asyncio.get_running_loop().time() <= deadline:
            return True

        logger.info(
            "Trailing PCM drain window expired before END arrived; resuming normal routing"
        )
        self._clear_trailing_pcm_drain()
        return False

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
