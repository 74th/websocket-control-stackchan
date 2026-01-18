from __future__ import annotations

from logging import StreamHandler, getLogger

from stackchan_server.app import StackChanApp
from stackchan_server.ws_proxy import WsProxy
from google import genai
from google.genai.types import HttpOptions, ModelContent, Part, UserContent


logger = getLogger(__name__)
logger.addHandler(StreamHandler())
logger.setLevel("DEBUG")


app = StackChanApp()


@app.setup
async def setup(proxy: WsProxy):
	logger.info("WebSocket connected")


@app.loop
async def loop(proxy: WsProxy):
	text = await proxy.get_message_async()
	logger.info("Heard: %s", text)
	await proxy.start_talking(text)



if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.echo:app.fastapi", host="0.0.0.0", port=8000, reload=True)
