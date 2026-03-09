from __future__ import annotations

import queue
import threading
from logging import getLogger

from google.cloud import speech

from ..types import SpeechRecognizer, StreamingSpeechRecognizer, StreamingSpeechSession

logger = getLogger(__name__)
_STREAM_END = object()


class _GoogleCloudStreamingSession(StreamingSpeechSession):
    def __init__(
        self,
        client: speech.SpeechClient,
        *,
        sample_rate_hz: int,
        channels: int,
        sample_width: int,
        language_code: str,
    ) -> None:
        if channels != 1:
            raise ValueError(f"Google Cloud Speech only supports mono input here: channels={channels}")
        if sample_width != 2:
            raise ValueError(
                f"Google Cloud Speech LINEAR16 requires 16-bit samples here: sample_width={sample_width}"
            )

        self._client = client
        self._config = speech.StreamingRecognitionConfig(
            config=speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=sample_rate_hz,
                language_code=language_code,
            ),
            interim_results=False,
            single_utterance=False,
        )
        self._audio_queue: queue.Queue[bytes | object] = queue.Queue()
        self._done = threading.Event()
        self._closed = False
        self._error: Exception | None = None
        self._final_transcripts: list[str] = []
        self._latest_transcript = ""
        self._thread = threading.Thread(target=self._run, name="gcloud-speech-stream", daemon=True)
        self._thread.start()

    def push_audio(self, pcm_bytes: bytes) -> None:
        if self._closed:
            raise RuntimeError("streaming speech session is already closed")
        if pcm_bytes:
            self._audio_queue.put(bytes(pcm_bytes))

    def finish(self) -> str:
        self._close_stream()
        self._thread.join(timeout=30.0)
        if self._thread.is_alive():
            raise TimeoutError("timed out waiting for streaming speech recognition to finish")
        if self._error is not None:
            raise self._error
        transcript = "".join(self._final_transcripts)
        return transcript or self._latest_transcript

    def abort(self) -> None:
        self._close_stream()
        self._done.wait(timeout=1.0)

    def _close_stream(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._audio_queue.put(_STREAM_END)

    def _request_iter(self):
        while True:
            chunk = self._audio_queue.get()
            if chunk is _STREAM_END:
                return
            yield speech.StreamingRecognizeRequest(audio_content=chunk)

    def _run(self) -> None:
        try:
            responses = self._client.streaming_recognize(self._config, self._request_iter())
            for response in responses:
                for result in response.results:
                    if not result.alternatives:
                        continue
                    transcript = result.alternatives[0].transcript
                    if result.is_final:
                        logger.info("Streaming transcript(final): %s", transcript)
                        self._final_transcripts.append(transcript)
                        self._latest_transcript = ""
                    else:
                        logger.info("Streaming transcript(interim): %s", transcript)
                        self._latest_transcript = transcript
        except Exception as exc:
            self._error = exc
        finally:
            self._done.set()


class GoogleCloudSpeechToText(StreamingSpeechRecognizer):
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

    def start_stream(
        self,
        *,
        sample_rate_hz: int,
        channels: int,
        sample_width: int,
        language_code: str = "ja-JP",
    ) -> StreamingSpeechSession:
        return _GoogleCloudStreamingSession(
            self._client,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
            sample_width=sample_width,
            language_code=language_code,
        )


__all__ = ["GoogleCloudSpeechToText"]
