from __future__ import annotations

import asyncio
from logging import getLogger
from typing import Awaitable, Callable, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .speech_recognition import create_speech_recognizer
from .speech_synthesis import create_speech_synthesizer
from .types import SpeechRecognizer, SpeechSynthesizer
from .ws_proxy import WsProxy

logger = getLogger(__name__)


class StackChanInfo(BaseModel):
    ip: str
    state: str


class SpeakRequest(BaseModel):
    text: str


class StackChanApp:
    def __init__(
        self,
        speech_recognizer: SpeechRecognizer | None = None,
        speech_synthesizer: SpeechSynthesizer | None = None,
    ) -> None:
        self.speech_recognizer = speech_recognizer or create_speech_recognizer()
        self.speech_synthesizer = speech_synthesizer or create_speech_synthesizer()
        self.fastapi = FastAPI(title="StackChan WebSocket Server")
        self._setup_fn: Optional[Callable[[WsProxy], Awaitable[None]]] = None
        self._talk_session_fn: Optional[Callable[[WsProxy], Awaitable[None]]] = None
        self._proxies: dict[str, WsProxy] = {}

        @self.fastapi.get("/health")
        async def _health() -> dict[str, str]:
            return {"status": "ok"}

        @self.fastapi.websocket("/ws/stackchan")
        async def _ws_audio(websocket: WebSocket):
            await self._handle_ws(websocket)

        @self.fastapi.get("/v1/stackchan", response_model=list[StackChanInfo])
        async def _list_stackchans():
            return [
                StackChanInfo(ip=ip, state=proxy.current_state.name.lower())
                for ip, proxy in self._proxies.items()
            ]

        @self.fastapi.get("/v1/stackchan/{stackchan_ip}", response_model=StackChanInfo)
        async def _get_stackchan(stackchan_ip: str):
            proxy = self._proxies.get(stackchan_ip)
            if proxy is None:
                raise HTTPException(status_code=404, detail="stackchan not connected")
            return StackChanInfo(ip=stackchan_ip, state=proxy.current_state.name.lower())

        @self.fastapi.post("/v1/stackchan/{stackchan_ip}/wakeword", status_code=204)
        async def _trigger_wakeword(stackchan_ip: str):
            proxy = self._proxies.get(stackchan_ip)
            if proxy is None:
                raise HTTPException(status_code=404, detail="stackchan not connected")
            proxy.trigger_wakeword()

        @self.fastapi.post("/v1/stackchan/{stackchan_ip}/speak", status_code=204)
        async def _speak(stackchan_ip: str, body: SpeakRequest):
            proxy = self._proxies.get(stackchan_ip)
            if proxy is None:
                raise HTTPException(status_code=404, detail="stackchan not connected")
            await proxy.speak(body.text)

    def setup(self, fn: Callable[["WsProxy"], Awaitable[None]]):
        self._setup_fn = fn
        return fn

    def talk_session(self, fn: Callable[["WsProxy"], Awaitable[None]]):
        self._talk_session_fn = fn
        return fn

    async def _handle_ws(self, websocket: WebSocket) -> None:
        await websocket.accept()
        client_ip = websocket.client.host if websocket.client else "unknown"

        # 同一 IP からの既存接続があれば切断する
        existing = self._proxies.get(client_ip)
        if existing is not None:
            logger.info("Duplicate connection from %s, closing old one", client_ip)
            await existing.close()
            self._proxies.pop(client_ip, None)

        proxy = WsProxy(
            websocket,
            speech_recognizer=self.speech_recognizer,
            speech_synthesizer=self.speech_synthesizer,
        )
        self._proxies[client_ip] = proxy
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
            self._proxies.pop(client_ip, None)

    def run(self, host: str = "0.0.0.0", port: int = 8000, reload: bool = True) -> None:
        import uvicorn

        # When passing an app instance, reload has no effect; kept for API compatibility.
        uvicorn.run(self.fastapi, host=host, port=port, reload=reload)


__all__ = ["StackChanApp"]
