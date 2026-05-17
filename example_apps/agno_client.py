from __future__ import annotations

import os
from functools import lru_cache
from importlib import import_module
from logging import StreamHandler, getLogger
from typing import Any

from dotenv import load_dotenv

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

AGNO_SERVER_URL = os.getenv("AGNO_SERVER_URL", "http://localhost:8000")
AGNO_AGENT_ID = os.getenv("AGNO_AGENT_ID", "workbench")
AGNO_USER_ID = os.getenv("AGNO_USER_ID")


@lru_cache(maxsize=1)
def _get_agno_client_class() -> type[Any]:
    try:
        return import_module("agno.client.os").AgentOSClient
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Agno is not installed. Install the optional dependencies for example-agno first."
        ) from exc


@lru_cache(maxsize=1)
def _get_agno_event_types() -> tuple[type[Any], type[Any]]:
    try:
        module = import_module("agno.run.agent")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Agno is not installed. Install the optional dependencies for example-agno first."
        ) from exc
    return module.RunContentEvent, module.RunCompletedEvent


async def generate_response(
    client: Any,
    message: str,
    session_id: str | None,
) -> tuple[str, str | None, str | None]:
    response_parts: list[str] = []
    run_id: str | None = None
    run_content_event, run_completed_event = _get_agno_event_types()

    async for event in client.run_agent_stream(
        agent_id=AGNO_AGENT_ID,
        message=message,
        session_id=session_id,
        user_id=AGNO_USER_ID,
    ):
        session_id = getattr(event, "session_id", session_id)

        if isinstance(event, run_content_event) and event.content:
            response_parts.append(event.content)
        elif isinstance(event, run_completed_event):
            run_id = event.run_id

    return "".join(response_parts).strip(), session_id, run_id


@app.setup
async def setup(proxy: WsProxy):
    logger.info("WebSocket connected")


@app.talk_session
async def talk_session(proxy: WsProxy):
    client = _get_agno_client_class()(base_url=AGNO_SERVER_URL)
    session_id: str | None = None

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
        response_text, session_id, run_id = await generate_response(
            client=client,
            message=text,
            session_id=session_id,
        )

        # speaking
        logger.info("AI: %s", response_text)
        if run_id:
            logger.info("Agno Run ID: %s", run_id)
        if session_id:
            logger.info("Agno Session ID: %s", session_id)
        if response_text:
            await proxy.speak(response_text)
