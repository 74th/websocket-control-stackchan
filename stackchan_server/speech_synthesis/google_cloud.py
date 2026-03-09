from __future__ import annotations

import io
import os
import wave
from collections.abc import AsyncIterator
from logging import getLogger
from typing import Any

from google import genai
from google.genai import types

from ..types import AudioFormat, StreamingSpeechSynthesizer

logger = getLogger(__name__)

_DEFAULT_MODEL = "gemini-2.5-flash-tts"
_DEFAULT_LOCATION = "global"
_PCM_SAMPLE_RATE_HZ = 24000
_PCM_CHANNELS = 1
_PCM_SAMPLE_WIDTH = 2
_OUTPUT_FORMAT = AudioFormat(
    sample_rate_hz=_PCM_SAMPLE_RATE_HZ,
    channels=_PCM_CHANNELS,
    sample_width=_PCM_SAMPLE_WIDTH,
)


def create_vertexai_client() -> Any:
    return genai.Client(
        vertexai=True,
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("GOOGLE_CLOUD_REGION") or _DEFAULT_LOCATION,
    ).aio


class GoogleCloudTextToSpeech(StreamingSpeechSynthesizer):
    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        language_code: str = "ja-JP",
        voice_name: str = "Despina",
        style_instructions: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._language_code = language_code
        self._voice_name = voice_name
        self._style_instructions = style_instructions
        self._client = client or create_vertexai_client()

    @property
    def output_format(self) -> AudioFormat:
        return _OUTPUT_FORMAT

    async def synthesize(self, text: str) -> bytes:
        pcm_bytes = bytearray()
        async for chunk in self.synthesize_stream(text):
            pcm_bytes.extend(chunk)
        logger.info(
            "Gemini TTS response pcm_bytes=%d model=%s language_code=%s voice_name=%s",
            len(pcm_bytes),
            self._model,
            self._language_code,
            self._voice_name,
        )
        return self._wrap_pcm_as_wav(bytes(pcm_bytes))

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        logger.info(
            "Requesting Gemini TTS model=%s language_code=%s voice_name=%s text_chars=%d",
            self._model,
            self._language_code,
            self._voice_name,
            len(text),
        )
        async for response in await self._client.models.generate_content_stream(
            model=self._model,
            contents=self._build_contents(text),
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    language_code=self._language_code,
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=self._voice_name,
                        )
                    ),
                ),
            ),
        ):
            chunk = self._extract_audio_bytes(response)
            if chunk:
                yield chunk

    def _build_contents(self, text: str) -> str:
        if not self._style_instructions:
            return text
        return f"{self._style_instructions}\n\n{text}"

    def _extract_audio_bytes(self, response: types.GenerateContentResponse) -> bytes:
        pcm_bytes = bytearray()
        if not response.candidates:
            return b""
        for candidate in response.candidates:
            if not candidate.content or not candidate.content.parts:
                continue
            for part in candidate.content.parts:
                if part.inline_data and isinstance(part.inline_data.data, bytes):
                    pcm_bytes.extend(part.inline_data.data)
        return bytes(pcm_bytes)

    def _wrap_pcm_as_wav(self, pcm_bytes: bytes) -> bytes:
        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as wav_fp:
                wav_fp.setnchannels(_PCM_CHANNELS)
                wav_fp.setsampwidth(_PCM_SAMPLE_WIDTH)
                wav_fp.setframerate(_PCM_SAMPLE_RATE_HZ)
                wav_fp.writeframes(pcm_bytes)
            return buffer.getvalue()


__all__ = ["GoogleCloudTextToSpeech", "create_vertexai_client"]
