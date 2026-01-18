from __future__ import annotations

from stackchan_server.app import StackChanApp, logger
from stackchan_server.ws_proxy import WsProxy


logic_app = StackChanApp()


@logic_app.setup
async def setup(proxy: WsProxy):
	logger.info("WebSocket connected")


@logic_app.loop
async def loop(proxy: WsProxy):
	text = await proxy.get_message_async()
	logger.info("Heard: %s", text)
	await proxy.start_talking(text)


fastapi_app = logic_app.fastapi

# FastAPI application export for uvicorn (app.main:app)
app = fastapi_app


def main() -> None:
	logic_app.run(host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
	main()
