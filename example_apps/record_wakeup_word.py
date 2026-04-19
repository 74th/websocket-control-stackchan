from __future__ import annotations

import asyncio
import logging
import os
import wave
from datetime import UTC, datetime
from logging import getLogger
from pathlib import Path

from dotenv import load_dotenv

from stackchan_server.app import StackChanApp
from stackchan_server.static import LISTEN_AUDIO_FORMAT
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
    duration_ms = 2500
    logger.info("Recording wakeup word duration_ms=%d", duration_ms)
    await proxy.speak(
        "これからウェイクアップワードの録音を開始します。ピッと鳴ったら、ウェイクアップワードを話してください。"
    )
    await proxy.speak(
        "50回録音します。トーンを変えたり、ちょっと遠くから話したりして、いろいろなパターンを録音してください。"
    )

    output_dir = Path("tmp")
    output_dir.mkdir(parents=True, exist_ok=True)

    for i in range(50):
        if i > 0 and i % 10 == 0:
            await proxy.speak(f"あと{50 - i}回")

        await proxy.tone(2000, 200)
        raw_audio = await proxy.listen_raw(duration=duration_ms)

        filename = f"wakeup_word_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}.wav"
        filepath = output_dir / filename

        with wave.open(str(filepath), "wb") as wav_fp:
            wav_fp.setnchannels(LISTEN_AUDIO_FORMAT.channels)
            wav_fp.setsampwidth(LISTEN_AUDIO_FORMAT.sample_width)
            wav_fp.setframerate(LISTEN_AUDIO_FORMAT.sample_rate_hz)
            wav_fp.writeframes(raw_audio)

        logger.info("Saved wakeup word recording to %s", filepath)

    await proxy.speak(
        "お疲れ様でした"
    )

    return {
        "path": str(filepath),
        "bytes": len(raw_audio),
        "sample_rate": LISTEN_AUDIO_FORMAT.sample_rate_hz,
        "channels": LISTEN_AUDIO_FORMAT.channels,
        "sample_width": LISTEN_AUDIO_FORMAT.sample_width,
        "duration_ms": duration_ms,
    }
