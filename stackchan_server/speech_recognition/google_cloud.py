from __future__ import annotations

import asyncio
from logging import getLogger

from google.cloud import speech

from ..types import StreamingSpeechRecognizer, StreamingSpeechSession

logger = getLogger(__name__)
_STREAM_END = object()


class _GoogleCloudStreamingSession(StreamingSpeechSession):
    def __init__(
        self,
        client: speech.SpeechAsyncClient,
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
        self._audio_queue: asyncio.Queue[bytes | object] = asyncio.Queue()
        self._done = asyncio.Event()
        self._closed = False
        self._error: Exception | None = None
        self._final_transcripts: list[str] = []
        self._latest_transcript = ""
        self._task = asyncio.create_task(self._run())

    async def push_audio(self, pcm_bytes: bytes) -> None:
        if self._closed:
            raise RuntimeError("streaming speech session is already closed")
        if pcm_bytes:
            await self._audio_queue.put(bytes(pcm_bytes))

    async def finish(self) -> str:
        await self._close_stream()
        await self._task
        if self._error is not None:
            raise self._error
        transcript = "".join(self._final_transcripts)
        return transcript or self._latest_transcript

    async def abort(self) -> None:
        await self._close_stream()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _close_stream(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._audio_queue.put(_STREAM_END)

    async def _request_iter(self):
        yield speech.StreamingRecognizeRequest(streaming_config=self._config)
        while True:
            chunk = await self._audio_queue.get()
            if chunk is _STREAM_END:
                break
            yield speech.StreamingRecognizeRequest(audio_content=chunk)

    async def _run(self) -> None:
        try:
            responses = await self._client.streaming_recognize(requests=self._request_iter())
            async for response in responses:
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
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._error = exc
        finally:
            self._done.set()


class GoogleCloudSpeechToText(StreamingSpeechRecognizer):
    def __init__(self, client: speech.SpeechAsyncClient | None = None) -> None:
        self._client = client or speech.SpeechAsyncClient()

    async def transcribe(
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
        response = await self._client.recognize(config=config, audio=audio)

        return "".join(result.alternatives[0].transcript for result in response.results)

    async def start_stream(
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
