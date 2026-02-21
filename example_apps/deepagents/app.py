from __future__ import annotations

import pathlib
from logging import StreamHandler, getLogger

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from google import genai
from google.genai import types
from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver

from stackchan_server.app import StackChanApp
from stackchan_server.ws_proxy import WsProxy

logger = getLogger(__name__)
logger.addHandler(StreamHandler())
logger.setLevel("DEBUG")

WORKSPACE_DIR = pathlib.Path(__file__).parent / "workspace"
SKILLS_DIR = WORKSPACE_DIR / "skills"

app = StackChanApp()

genai_client = genai.Client().aio


@tool(
    "google_search",
    description="Google検索を行うツール。自然言語の質問で聞ける。",
    args_schema={"query": str},
)
async def google_search(query: str):
    grounding_tool = types.Tool(google_search=types.GoogleSearch())

    config = types.GenerateContentConfig(tools=[grounding_tool])

    response = await genai_client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=query,
        config=config,
    )

    return response.text


instruction = """あなたは自宅に置かれている音声で応答する日本語のAIホームエージェントです。以下のように振る舞ってください。
- 音声エージェントであるため、ユーザーへの応答はすべて日本語で、マークダウンのように構造化された形式ではなく、自然な会話形式で行ってください。
- 音声応答は3文程度に収めてください。
- **スキルは関連性がありそうであれば必ず参照すること**
- スキルを呼び出すときには、スキルを呼び出すことを明示的に宣言する必要はありません。
"""

agent = create_deep_agent(
    backend=FilesystemBackend(root_dir=WORKSPACE_DIR.as_posix()),
    # Gemini
    model=ChatGoogleGenerativeAI(model="gemini-3-flash-preview"),
    tools=[google_search],
    skills=[SKILLS_DIR.as_posix()],
    system_prompt=instruction,
    checkpointer=MemorySaver(),
)


@app.setup
async def setup(proxy: WsProxy):
    logger.info("WebSocket connected")


@app.talk_session
async def talk_session(proxy: WsProxy):
    config = {"configurable": {"thread_id": "my-thread"}}

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
