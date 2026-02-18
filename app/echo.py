from __future__ import annotations

from logging import StreamHandler, getLogger

from stackchan_server.app import StackChanApp
from stackchan_server.ws_proxy import WsProxy


logger = getLogger(__name__)
logger.addHandler(StreamHandler())
logger.setLevel("DEBUG")


app = StackChanApp()


@app.setup
async def setup(proxy: WsProxy):
    logger.info("WebSocket connected")


@app.talk_session
async def talk_session(proxy: WsProxy):
    text = await proxy.listen()
    logger.info("Heard: %s", text)
    await proxy.speak(text)

    while True:
        text = await proxy.listen()
        if not text:
            return
        logger.info("Heard: %s", text)
        await proxy.speak(text)



if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.echo:app.fastapi", host="0.0.0.0", port=8000, reload=True)
