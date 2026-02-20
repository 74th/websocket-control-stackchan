from __future__ import annotations

from logging import StreamHandler, getLogger

from google import genai
from google.genai import types

from stackchan_server.app import StackChanApp
from stackchan_server.ws_proxy import WsProxy

logger = getLogger(__name__)
logger.addHandler(StreamHandler())
logger.setLevel("DEBUG")


app = StackChanApp()

client = genai.Client(vertexai=True).aio

@app.setup
async def setup(proxy: WsProxy):
    logger.info("WebSocket connected")

@app.talk_session
async def talk_session(proxy: WsProxy):
    chat = client.chats.create(
        model="gemini-3-flash-preview",
        config=types.GenerateContentConfig(
            system_instruction="あなたは親切な音声アシスタントです。音声で返答するため、マークダウンは記述せず、簡潔に答えてください。だいたい3文程度で答えてください。",
        ),
    )

    while True:
        text = await proxy.listen()
        if not text:
            return
        logger.info("Human: %s", text)

        # AI応答の取得
        resp = await chat.send_message(text)

        # 発話
        logger.info("AI: %s", resp.text)
        if resp.text:
            await proxy.speak(resp.text)



if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.gemini:app.fastapi", host="0.0.0.0", port=8000, reload=True)
