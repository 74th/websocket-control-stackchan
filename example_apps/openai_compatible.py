from __future__ import annotations

import os
from logging import StreamHandler, getLogger

from dotenv import load_dotenv
from openai import AsyncOpenAI

from stackchan_server.app import StackChanApp
from stackchan_server.ws_proxy import (
    EmptyTranscriptError,
    ServoMoveType,
    ServoWaitType,
    WsProxy,
)

logger = getLogger(__name__)
logger.addHandler(StreamHandler())
logger.setLevel("DEBUG")

load_dotenv()

app = StackChanApp()

client = AsyncOpenAI(
    base_url=os.getenv("OPENAI_BASE_URL", ""),
    api_key=os.getenv("OPENAI_API_KEY", ""),
)

MODEL = os.getenv("OPENAI_MODEL", "")

SYSTEM_PROMPT = "あなたは親切な音声アシスタントです。音声で返答するため、マークダウンは記述せず、簡潔に答えてください。だいたい3文程度で答えてください。"


@app.setup
async def setup(proxy: WsProxy):
    logger.info("WebSocket connected")


@app.talk_session
async def talk_session(proxy: WsProxy):
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    while True:
        # listening pose
        await proxy.move_servo([(ServoMoveType.MOVE_Y, 80, 100)])

        try:
            # voice recognition
            text = await proxy.listen()

        except EmptyTranscriptError:
            # off pose
            await proxy.move_servo([(ServoMoveType.MOVE_Y, 90, 100)])
            return

        # nod pose
        await proxy.move_servo(
            [
                (ServoMoveType.MOVE_Y, 100, 100),
                (ServoWaitType.SLEEP, 200),
                (ServoMoveType.MOVE_Y, 90, 100),
                (ServoWaitType.SLEEP, 200),
                (ServoMoveType.MOVE_Y, 100, 100),
                (ServoWaitType.SLEEP, 200),
                (ServoMoveType.MOVE_Y, 90, 100),
            ]
        )

        logger.info("Human: %s", text)

        messages.append({"role": "user", "content": text})

        # generate response via OpenAI-compatible API (LM Studio)
        resp = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
        )

        reply = resp.choices[0].message.content or ""

        messages.append({"role": "assistant", "content": reply})

        # speaking
        logger.info("AI: %s", reply)
        if reply:
            await proxy.speak(reply)
