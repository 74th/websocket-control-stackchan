from __future__ import annotations

import asyncio
from logging import getLogger
from typing import Any, Awaitable, Callable, Optional

from .wakeup_word_detection import (
    WakeWordDetectionError,
    WakeWordDetectionTimeout,
    create_server_side_wake_word_detector,
)

logger = getLogger(__name__)

_SERVER_WAKEWORD_RESTART_DELAY_SECONDS = 0.25
_TRAILING_PCM_DRAIN_SECONDS = 1.0


class ServerWwdController:
    def __init__(
        self,
        *,
        send_state_command: Callable[[int], Awaitable[None]],
        set_current_state: Callable[[int], None],
        close_websocket: Callable[[int, str], Awaitable[None]],
        current_state: Callable[[], int],
        is_closed: Callable[[], bool],
        on_detected: Callable[[], None],
        server_wwd_state: int,
        idle_state: int,
    ) -> None:
        self._send_state_command = send_state_command
        self._set_current_state = set_current_state
        self._close_websocket = close_websocket
        self._current_state = current_state
        self._is_closed = is_closed
        self._on_detected = on_detected
        self._server_wwd_state = server_wwd_state
        self._idle_state = idle_state

        self._detector = create_server_side_wake_word_detector()
        self._task: Optional[asyncio.Task[bool]] = None
        self._restart_task: Optional[asyncio.Task[None]] = None
        self._auto_start = False
        self._suppress_restart_once = False
        self._drain_trailing_pcm_until_end = False
        self._drain_trailing_pcm_deadline: float | None = None

    @property
    def available(self) -> bool:
        return self._detector is not None

    @property
    def auto_start_enabled(self) -> bool:
        return self._auto_start

    async def enable_auto_detection(self) -> None:
        self._auto_start = True

    async def start_if_available(self) -> bool:
        if (
            self._is_closed()
            or self._detector is None
            or self._current_state() != self._idle_state
        ):
            return False

        if self._task is not None and not self._task.done():
            return True

        self._cancel_restart_task()
        self._task = asyncio.create_task(
            self._run_detection(),
            name="server-side-wakeword-detection",
        )
        return True

    async def stop(self, *, suppress_restart: bool = True) -> None:
        self._cancel_restart_task()
        task = self._task
        if task is None:
            return

        if suppress_restart and not task.done():
            self._suppress_restart_once = True

        if task.done():
            self._task = None
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Server-side wake-word detection task failed")
            return

        task.cancel()
        self._task = None
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Server-side wake-word detection task failed")

    async def handle_pcm_message(self, message: Any, *, ws_pb2: Any) -> bool:
        body_name = message.WhichOneof("body")

        if self._should_drain_trailing_pcm():
            if (
                message.message_type == ws_pb2.MESSAGE_TYPE_START
                and body_name == "audio_pcm_start"
            ):
                logger.info(
                    "Received a new server-side wake-word PCM START while draining trailing audio; resuming normal routing"
                )
                self._clear_trailing_pcm_drain()
            elif (
                message.message_type == ws_pb2.MESSAGE_TYPE_DATA
                and body_name == "audio_pcm_data"
            ):
                logger.info(
                    "Discarding trailing server-side wake-word PCM DATA payload_bytes=%d",
                    len(message.audio_pcm_data.pcm_bytes),
                )
                return True
            elif (
                message.message_type == ws_pb2.MESSAGE_TYPE_END
                and body_name == "audio_pcm_end"
            ):
                logger.info("Finished draining trailing server-side wake-word PCM")
                self._clear_trailing_pcm_drain()
                return True

        detector = self._detector
        if detector is None or not detector.running:
            logger.info(
                "Ignoring server-side wake-word PCM while detector is inactive type=%s body=%s",
                message.message_type,
                body_name,
            )
            return True

        if (
            message.message_type == ws_pb2.MESSAGE_TYPE_START
            and body_name == "audio_pcm_start"
        ):
            await detector.handle_start()
            return True

        if (
            message.message_type == ws_pb2.MESSAGE_TYPE_DATA
            and body_name == "audio_pcm_data"
        ):
            payload = bytes(message.audio_pcm_data.pcm_bytes)
            await detector.handle_data(payload)
            return True

        if (
            message.message_type == ws_pb2.MESSAGE_TYPE_END
            and body_name == "audio_pcm_end"
        ):
            await detector.handle_end()
            return True

        await self._close_websocket(1003, "unknown server wake-word PCM protobuf body")
        return False

    def schedule_restart(
        self,
        delay_seconds: float = _SERVER_WAKEWORD_RESTART_DELAY_SECONDS,
    ) -> None:
        if not self._auto_start or self._is_closed():
            return

        self._cancel_restart_task()
        self._restart_task = asyncio.create_task(
            self._restart_after_delay(delay_seconds),
            name="server-side-wakeword-restart",
        )

    async def _run_detection(self) -> bool:
        detector = self._detector
        if detector is None:
            return False

        detected = False
        should_restart = False
        try:
            await detector.start()
            await self._send_state_command(self._server_wwd_state)
            detected = await detector.wait_result()
            if detected:
                self._on_detected()
            return detected
        except asyncio.CancelledError:
            raise
        except WakeWordDetectionTimeout as exc:
            logger.info("Server-side wake-word detection stopped: %s", exc)
            return False
        except WakeWordDetectionError as exc:
            logger.warning("Server-side wake-word detection stopped: %s", exc)
            return False
        except Exception:
            logger.exception("Server-side wake-word detection failed")
            return False
        finally:
            await detector.stop()
            self._arm_trailing_pcm_drain()
            if not self._is_closed():
                self._set_current_state(self._idle_state)
                try:
                    await self._send_state_command(self._idle_state)
                except Exception:
                    logger.exception(
                        "Failed to return firmware to idle after wake-word detection"
                    )
            suppress_restart = self._suppress_restart_once
            self._suppress_restart_once = False
            should_restart = (
                self._auto_start
                and not detected
                and not suppress_restart
                and not self._is_closed()
            )
            if self._task is asyncio.current_task():
                self._task = None
            if should_restart:
                self.schedule_restart()

    def _cancel_restart_task(self) -> None:
        task = self._restart_task
        if task is None:
            return
        self._restart_task = None
        task.cancel()

    async def _restart_after_delay(self, delay_seconds: float) -> None:
        try:
            await asyncio.sleep(delay_seconds)
            if self._is_closed():
                return
            await self.start_if_available()
        except asyncio.CancelledError:
            raise
        finally:
            if self._restart_task is asyncio.current_task():
                self._restart_task = None

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


__all__ = ["ServerWwdController"]
