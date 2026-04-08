from __future__ import annotations

import os
import pathlib
from logging import StreamHandler, getLogger

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
)
from dotenv import load_dotenv

from stackchan_server.app import StackChanApp
from stackchan_server.ws_proxy import (
    EmptyTranscriptError,
    ServoMoveType,
    ServoWaitType,
    WsProxy,
)

load_dotenv()

logger = getLogger(__name__)
logger.addHandler(StreamHandler())
logger.setLevel("DEBUG")

WORKSPACE_DIR = pathlib.Path(__file__).parent / "workspace"


app = StackChanApp()

model = "claude-haiku-4-5-20251001"
if os.environ.get("CLAUDE_CODE_USE_VERTEX") == "1":
    model = "claude-haiku-4-5@20251001"


option = ClaudeAgentOptions(
    model=model,
    system_prompt="あなたは音声AIアシスタントのスタックチャンです。ユーザの質問に対して、3文程度の言葉で答えてください。音声案内であるため、マークダウンや絵文字等は用いずに、文字列だけで回答してください",
    cwd=str(WORKSPACE_DIR),
    setting_sources=["project"],
    permission_mode="bypassPermissions",
)

client = ClaudeSDKClient(
    options=option,
)


@app.setup
async def setup(proxy: WsProxy):
    logger.info("WebSocket connected")


@app.talk_session
async def talk_session(proxy: WsProxy):
    async with client:
        while True:
            await proxy.move_servo([(ServoMoveType.MOVE_Y, 80, 100)])

            try:
                text = await proxy.listen()
            except EmptyTranscriptError:
                await proxy.move_servo([(ServoMoveType.MOVE_Y, 90, 100)])
                logger.info("音声が聞き取れませんでした")
                return

            logger.info("Human: %s", text)

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

            # AI応答の取得
            await client.query(text)
            async for message in client.receive_response():
                logger.info(message)

                if isinstance(message, ResultMessage):
                    # 発話
                    logger.info("AI: %s", message.result)
                    if message.result:
                        await proxy.speak(message.result)
