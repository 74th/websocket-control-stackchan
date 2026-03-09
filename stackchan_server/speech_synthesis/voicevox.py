from __future__ import annotations

import os

from vvclient import Client as VVClient

from ..types import SpeechSynthesizer


def create_voicevox_client() -> VVClient:
    voicevox_url = os.getenv("STACKCHAN_VOICEVOX_URL", "http://localhost:50021")
    return VVClient(base_uri=voicevox_url)


class VoiceVoxSpeechSynthesizer(SpeechSynthesizer):
    def __init__(self, speaker: int = 29) -> None:
        self._speaker = speaker

    async def synthesize(self, text: str) -> bytes:
        async with create_voicevox_client() as client:
            audio_query = await client.create_audio_query(text, speaker=self._speaker)
            return await audio_query.synthesis(speaker=self._speaker)


__all__ = ["VoiceVoxSpeechSynthesizer", "create_voicevox_client"]
