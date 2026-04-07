from __future__ import annotations

from pydantic_settings import BaseSettings
from vvclient import Client as VVClient

from ..types import SpeechSynthesizer


class VoiceVoxSpeechSynthesizerConfig(BaseSettings):
    url: str = "http://localhost:50021"
    speaker: int = 29

    class Config:
        env_prefix = "STACKCHAN_VOICEVOX_"


class VoiceVoxSpeechSynthesizer(SpeechSynthesizer):
    def __init__(
            self,
            config: VoiceVoxSpeechSynthesizerConfig | None = None,
            ) -> None:
        self._conf = config or VoiceVoxSpeechSynthesizerConfig()

    def create_voicevox_client(self) -> VVClient:
        return VVClient(base_uri=self._conf.url)

    async def synthesize(self, text: str) -> bytes:
        async with self.create_voicevox_client() as client:
            audio_query = await client.create_audio_query(text, speaker=self._conf.speaker)
            return await audio_query.synthesis(speaker=self._conf.speaker)


__all__ = ["VoiceVoxSpeechSynthesizer"]
