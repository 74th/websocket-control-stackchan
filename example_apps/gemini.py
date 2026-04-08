from __future__ import annotations

from logging import StreamHandler, getLogger

from dotenv import load_dotenv
from google import genai
from google.genai import types

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

        # generate response
        resp = await chat.send_message(text)

        # speaking
        logger.info("AI: %s", resp.text)
        if resp.text:
            await proxy.speak(resp.text)
