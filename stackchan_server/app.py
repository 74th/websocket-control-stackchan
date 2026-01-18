from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google.cloud import speech

from .ws_proxy import WsProxy


class StackChanApp:
    def __init__(self) -> None:
        self.speech_client = speech.SpeechClient()
        self.fastapi = FastAPI(title="StackChan WebSocket Server")
        self._setup_fn: Optional[Callable[[WsProxy], Awaitable[None]]] = None
        self._loop_fn: Optional[Callable[[WsProxy], Awaitable[None]]] = None

        @self.fastapi.get("/health")
        async def _health() -> dict[str, str]:
            return {"status": "ok"}

        @self.fastapi.websocket("/ws/stackchan")
        async def _ws_audio(websocket: WebSocket):
            await self._handle_ws(websocket)

    def setup(self, fn: Callable[["WsProxy"], Awaitable[None]]):
        self._setup_fn = fn
        return fn

    def loop(self, fn: Callable[["WsProxy"], Awaitable[None]]):
        self._loop_fn = fn
        return fn

    async def _handle_ws(self, websocket: WebSocket) -> None:
        await websocket.accept()
        proxy = WsProxy(websocket, speech_client=self.speech_client)
        await proxy.start()
        try:
            if self._setup_fn:
                await self._setup_fn(proxy)

            while not proxy.closed:
                if self._loop_fn:
                    await self._loop_fn(proxy)
                else:
                    await asyncio.sleep(0.05)

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
