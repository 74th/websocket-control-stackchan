from __future__ import annotations

from google.cloud import speech

from ..types import SpeechRecognizer


class GoogleCloudSpeechToText(SpeechRecognizer):
    def __init__(self, client: speech.SpeechClient | None = None) -> None:
        self._client = client or speech.SpeechClient()

    def transcribe(
        self,
        pcm_bytes: bytes,
        *,
        sample_rate_hz: int,
        channels: int,
        sample_width: int,
        language_code: str = "ja-JP",
    ) -> str:
        if channels != 1:
            raise ValueError(f"Google Cloud Speech only supports mono input here: channels={channels}")
        if sample_width != 2:
            raise ValueError(
                f"Google Cloud Speech LINEAR16 requires 16-bit samples here: sample_width={sample_width}"
            )

        audio = speech.RecognitionAudio(content=pcm_bytes)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate_hz,
            language_code=language_code,
        )
        response = self._client.recognize(config=config, audio=audio)

        return "".join(result.alternatives[0].transcript for result in response.results)


__all__ = ["GoogleCloudSpeechToText"]
