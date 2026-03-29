from __future__ import annotations

import os
import pathlib
from logging import StreamHandler, getLogger
from typing import Any, Literal

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    create_sdk_mcp_server,
    tool,
)
from pydantic import BaseModel

from stackchan_server.app import StackChanApp
from stackchan_server.speech_recognition.whisper_cpp import WhisperCppSpeechToText
from stackchan_server.speech_synthesis.voicevox import VoiceVoxSpeechSynthesizer
from stackchan_server.ws_proxy import (
    EmptyTranscriptError,
    ServoMoveType,
    ServoWaitType,
    WsProxy,
)

logger = getLogger(__name__)
logger.addHandler(StreamHandler())
logger.setLevel("DEBUG")

WORKSPACE_DIR = pathlib.Path(__file__).parent / "workspace"


def _create_app() -> StackChanApp:
    whisper_model = os.getenv("STACKCHAN_WHISPER_MODEL")
    if whisper_model:
        return StackChanApp(
            speech_recognizer=WhisperCppSpeechToText(
                model_path=whisper_model,
            ),
            speech_synthesizer=VoiceVoxSpeechSynthesizer(),
        )
    return StackChanApp()

app = _create_app()

model = "claude-haiku-4-5-20251001"
if os.environ.get("CLAUDE_CODE_USE_VERTEX") == "1":
    model = "claude-haiku-4-5@20251001"


# ツールの作成
class AirConRemoteInput(BaseModel):
    room: Literal["寝室", "リビング"]
    state: Literal["オフ", "暖房オン", "冷房オン"]


@tool(
    "aircon-control",
    "自宅のエアコンを操作する。寝室かリビングかを指定する。",
    AirConRemoteInput.model_json_schema(),
)
async def aircon_remote(dict_args: dict[str, Any]):
    args = AirConRemoteInput.model_validate(dict_args)
    # 実際に実装が必要
    print(f"🌳エアコンを操作します {args}")
    return {"state": "success"}


# MCPサーバ化
home_remote_mcp = create_sdk_mcp_server(
    name="home-remote",
    version="1.0.0",
    tools=[aircon_remote],
)

def setup_claude_agent_sdk() -> ClaudeSDKClient:
    option = ClaudeAgentOptions(
        model=model,
        system_prompt="あなたは音声AIアシスタントのスタックチャンです。ユーザの質問に対して、3文程度の言葉で答えてください。音声案内であるため、マークダウンや絵文字等は用いずに、文字列だけで回答してください",
        cwd=str(WORKSPACE_DIR),
        setting_sources=["project"],

        # MCPサーバを登録
        mcp_servers={"home-remote": home_remote_mcp},
        # tools=["mcp__home-remote__aircon-control"],

        # 全て許可
        permission_mode="bypassPermissions",
    )

    return ClaudeSDKClient(
        options=option,
    )


client = setup_claude_agent_sdk()


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

            await proxy.move_servo([
                (ServoMoveType.MOVE_Y, 100, 100),
                (ServoWaitType.SLEEP, 200),
                (ServoMoveType.MOVE_Y, 90, 100),
                (ServoWaitType.SLEEP, 200),
                (ServoMoveType.MOVE_Y, 100, 100),
                (ServoWaitType.SLEEP, 200),
                (ServoMoveType.MOVE_Y, 90, 100),
            ])

            # AI応答の取得
            await client.query(text)
            async for message in client.receive_response():
                logger.info(message)

                if isinstance(message, ResultMessage):

                    # 発話
                    logger.info("AI: %s", message.result)
                    if message.result:
                        await proxy.speak(message.result)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "example_apps.claude_agent_sdk.claude_agent_sdk:app.fastapi",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
