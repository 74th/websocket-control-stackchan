from __future__ import annotations

import asyncio
from logging import StreamHandler, getLogger

from stackchan_server.app import StackChanApp
from stackchan_server.ws_proxy import WsProxy
from google import genai
from google.genai import types

logger = getLogger(__name__)
logger.addHandler(StreamHandler())
logger.setLevel("DEBUG")


app = StackChanApp()

client = genai.Client(vertexai=True)

@app.setup
async def setup(proxy: WsProxy):
    global chat
    logger.info("WebSocket connected")

    chat = client.chats.create(
        model="gemini-3-flash-preview",
        config=types.GenerateContentConfig(
            system_instruction="あなたは親切な音声アシスタントです。音声で返答するため、マークダウンは記述せず、簡潔に答えてください。だいたい3文程度で答えてください。",
        ),
    )

@app.loop
async def loop(proxy: WsProxy):
    global chat

    # 音声の受信
    text = await proxy.get_message_async()
    logger.info("Human: %s", text)

    # AI応答の取得
    resp = await asyncio.to_thread(chat.send_message, text)

    # 発話
    logger.info("AI: %s", resp.text)
    if resp.text:
        await proxy.start_talking(resp.text)
    else:
        await proxy.start_talking("すみません、うまく答えられませんでした。")



if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.echo:app.fastapi", host="0.0.0.0", port=8000, reload=True)
