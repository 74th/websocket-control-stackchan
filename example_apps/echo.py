from __future__ import annotations

import logging
import os
from logging import getLogger

from stackchan_server.app import StackChanApp
from stackchan_server.speech_recognition import (
    WhisperCppSpeechToText,
)
from stackchan_server.speech_synthesis import VoiceVoxSpeechSynthesizer
from stackchan_server.ws_proxy import EmptyTranscriptError, WsProxy

logger = getLogger(__name__)
logging.basicConfig(
    level=os.getenv("STACKCHAN_LOG_LEVEL", "INFO"),
    format="%(asctime)s.%(msecs)03d %(levelname)s:%(name)s:%(message)s",
    datefmt="%H:%M:%S",
)

def _create_app() -> StackChanApp:
    whisper_model = os.getenv("STACKCHAN_WHISPER_MODEL")
    # if os.getenv("STACKCHAN_WHISPER_SERVER_URL") or os.getenv("STACKCHAN_WHISPER_SERVER_PORT"):
    #     return StackChanApp(
    #         speech_recognizer=WhisperServerSpeechToText(server_url=whisper_server_url),
    #         speech_synthesizer=VoiceVoxSpeechSynthesizer(),
    #     )
    if whisper_model:
        return StackChanApp(
            speech_recognizer=WhisperCppSpeechToText(
                model_path=whisper_model,
            ),
            speech_synthesizer=VoiceVoxSpeechSynthesizer(),
        )
    return StackChanApp()


app = _create_app()


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



if __name__ == "__main__":
    import uvicorn

    uvicorn.run("example_apps.echo:app.fastapi", host="0.0.0.0", port=8000, reload=True)
