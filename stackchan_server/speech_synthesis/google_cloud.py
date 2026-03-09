from __future__ import annotations

from google.cloud import texttospeech

from ..types import SpeechSynthesizer

_AUDIO_ENCODING = texttospeech.AudioEncoding.LINEAR16
_SAMPLE_RATE_HZ = 16000


class GoogleCloudTextToSpeech(SpeechSynthesizer):
    def __init__(
        self,
        *,
        language_code: str = "ja-JP",
        voice_name: str = "ja-JP-Neural2-B",
        speaking_rate: float | None = None,
        pitch: float | None = None,
        client: texttospeech.TextToSpeechAsyncClient | None = None,
    ) -> None:
        self._language_code = language_code
        self._voice_name = voice_name
        self._speaking_rate = speaking_rate
        self._pitch = pitch
        self._client = client or texttospeech.TextToSpeechAsyncClient()

    async def synthesize(self, text: str) -> bytes:
        audio_config = texttospeech.AudioConfig(
            audio_encoding=_AUDIO_ENCODING,
            sample_rate_hertz=_SAMPLE_RATE_HZ,
        )
        if self._speaking_rate is not None:
            audio_config.speaking_rate = self._speaking_rate
        if self._pitch is not None:
            audio_config.pitch = self._pitch

        response = await self._client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=text),
            voice=texttospeech.VoiceSelectionParams(
                language_code=self._language_code,
                name=self._voice_name,
            ),
            audio_config=audio_config,
        )
        return bytes(response.audio_content)


__all__ = ["GoogleCloudTextToSpeech"]
