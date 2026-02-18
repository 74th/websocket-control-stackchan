from __future__ import annotations

import asyncio
from logging import getLogger
from typing import Awaitable, Callable, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google.cloud import speech

from .ws_proxy import WsProxy

logger = getLogger(__name__)


class StackChanApp:
    def __init__(self) -> None:
        self.speech_client = speech.SpeechClient()
        self.fastapi = FastAPI(title="StackChan WebSocket Server")
        self._setup_fn: Optional[Callable[[WsProxy], Awaitable[None]]] = None
        self._talk_session_fn: Optional[Callable[[WsProxy], Awaitable[None]]] = None

        @self.fastapi.get("/health")
        async def _health() -> dict[str, str]:
            return {"status": "ok"}

        @self.fastapi.websocket("/ws/stackchan")
        async def _ws_audio(websocket: WebSocket):
            await self._handle_ws(websocket)

    def setup(self, fn: Callable[["WsProxy"], Awaitable[None]]):
        self._setup_fn = fn
        return fn

    def talk_session(self, fn: Callable[["WsProxy"], Awaitable[None]]):
        self._talk_session_fn = fn
        return fn

    async def _handle_ws(self, websocket: WebSocket) -> None:
        await websocket.accept()
        proxy = WsProxy(websocket, speech_client=self.speech_client)
        await proxy.start()
        try:
            if self._setup_fn:
                await self._setup_fn(proxy)

            while not proxy.closed:
                if not self._talk_session_fn:
                    await asyncio.sleep(0.05)
                else:
                    await proxy.wait_for_talk_session()
                    disconnected = False
                    try:
                        await self._talk_session_fn(proxy)
                    except WebSocketDisconnect:
                        disconnected = True
                        raise
                    except Exception:
                        logger.exception("talk_session failed")
                    finally:
                        if not disconnected and not proxy.closed:
                            try:
                                await proxy.reset_state()
                            except WebSocketDisconnect:
                                disconnected = True
                            except Exception:
                                logger.exception("reset_state failed")

                if proxy.receive_task and proxy.receive_task.done():
                    break
        except WebSocketDisconnect:
            pass
        finally:
            await proxy.close()

    def run(self, host: str = "0.0.0.0", port: int = 8000, reload: bool = True) -> None:
        import uvicorn

        # When passing an app instance, reload has no effect; kept for API compatibility.
        uvicorn.run(self.fastapi, host=host, port=port, reload=reload)


__all__ = ["StackChanApp"]
