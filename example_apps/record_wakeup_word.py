from __future__ import annotations

import logging
import os
from logging import getLogger
from this import d

from dotenv import load_dotenv

from stackchan_server.app import StackChanApp
from stackchan_server.ws_proxy import EmptyTranscriptError, WsProxy

logger = getLogger(__name__)
logging.basicConfig(
    level=os.getenv("STACKCHAN_LOG_LEVEL", "INFO"),
    format="%(asctime)s.%(msecs)03d %(levelname)s:%(name)s:%(message)s",
    datefmt="%H:%M:%S",
)

load_dotenv()


app = StackChanApp()


@app.setup
async def setup(proxy: WsProxy):
    logger.info("WebSocket connected")


@app.talk_session
async def talk_session(proxy: WsProxy):
    while True:
        try:
            text = await proxy.listen()
        except EmptyTranscriptError:
            return
        if not text:
            return
        logger.info("Heard: %s", text)
        await proxy.speak(text)

@app.webapi("/record_wakeup_word")
async def record_wakeup_word(proxy: WsProxy, args: dict):
    logger.info("Recording wakeup word...")
    await proxy.speak("これからウェイクアップワードの録音を開始します。ピッと鳴ったら、ウェイクアップワードを話してください。")
    await proxy.tone(4000, 200)
    raw_audio = await proxy.listen_raw(duration=3000)  # 3秒間録音
    await proxy.tone(1000, 200)
