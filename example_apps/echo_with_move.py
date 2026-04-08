from __future__ import annotations

import logging
import os
from logging import getLogger

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
logging.basicConfig(
    level=os.getenv("STACKCHAN_LOG_LEVEL", "INFO"),
    format="%(asctime)s.%(msecs)03d %(levelname)s:%(name)s:%(message)s",
    datefmt="%H:%M:%S",
)

app = StackChanApp()


@app.setup
async def setup(proxy: WsProxy):
    logger.info("WebSocket connected")
    await proxy.move_servo([(ServoMoveType.MOVE_Y, 90, 100)])


@app.talk_session
async def talk_session(proxy: WsProxy):
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

        logger.info("Heard: %s", text)

        # speaking
        await proxy.speak(text)
