from __future__ import annotations

import asyncio
import json
import math
import mimetypes
import os
import uuid
from collections.abc import Mapping
from logging import getLogger
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..static import LISTEN_AUDIO_FORMAT, LISTEN_LANGUAGE_CODE
from ..types import SpeechRecognizer

logger = getLogger(__name__)

_DEFAULT_SILENCE_RMS_THRESHOLD = 75.0
_DEFAULT_SERVER_PORT = 8080


class WhisperServerSpeechToText(SpeechRecognizer):
    def __init__(
        self,
        *,
        server_url: str | None = None,
        language: str | None = None,
        detect_language: bool = False,
        response_format: str = "verbose_json",
        silence_rms_threshold: float = _DEFAULT_SILENCE_RMS_THRESHOLD,
        request_timeout_seconds: float = 60.0,
    ) -> None:
        self._server_url = server_url or _default_server_url()
        self._language = language or _normalize_language(LISTEN_LANGUAGE_CODE)
        self._detect_language = detect_language
        self._response_format = response_format
        self._silence_rms_threshold = silence_rms_threshold
        self._request_timeout_seconds = request_timeout_seconds

    async def transcribe(self, pcm_bytes: bytes) -> str:
        rms_level = _pcm_rms_level(pcm_bytes)
        if rms_level < self._silence_rms_threshold:
            logger.info(
                "Skipping whisper-server transcription because pcm rms %.2f is below silence threshold %.2f",
                rms_level,
                self._silence_rms_threshold,
            )
            return ""

        wav_bytes = _wrap_pcm_as_wav(
            pcm_bytes,
            sample_rate_hz=LISTEN_AUDIO_FORMAT.sample_rate_hz,
            channels=LISTEN_AUDIO_FORMAT.channels,
            sample_width=LISTEN_AUDIO_FORMAT.sample_width,
        )
        transcript = await asyncio.to_thread(
            self._request_transcript,
            wav_bytes,
            self._language,
        )
        if transcript:
            logger.info("whisper-server transcript: %s", transcript)
        return transcript

    def _request_transcript(self, wav_bytes: bytes, language: str) -> str:
        fields = {
            "response_format": self._response_format,
            "language": language,
        }
        if self._detect_language:
            fields["detect_language"] = "true"

        body, content_type = _encode_multipart_formdata(
            fields=fields,
            files={"file": ("input.wav", wav_bytes, "audio/wav")},
        )
        request = Request(
            self._server_url,
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        logger.info("Running whisper-server request: POST %s", self._server_url)
        try:
            with urlopen(request, timeout=self._request_timeout_seconds) as response:
                response_body = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"whisper-server failed: status={exc.code} body={detail or '<empty>'}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"whisper-server request failed: {exc.reason}") from exc

        if self._response_format == "json":
            payload = _load_json_response_bytes(response_body)
            if not isinstance(payload, Mapping):
                return ""
            payload = cast(Mapping[str, object], payload)
            text = payload.get("text")
            return text.strip() if isinstance(text, str) else ""

        payload = _load_json_response_bytes(response_body)
        return _load_transcript_from_verbose_json(payload)


def _default_server_url() -> str:
    configured = os.getenv("STACKCHAN_WHISPER_SERVER_URL")
    if configured:
        return configured.rstrip("/")
    port = os.getenv("STACKCHAN_WHISPER_SERVER_PORT", str(_DEFAULT_SERVER_PORT))
    return f"http://127.0.0.1:{port}/inference"


def _normalize_language(language_code: str) -> str:
    if not language_code:
        return ""
    return language_code.split("-", 1)[0].lower()


def _load_json_response_bytes(response_body: bytes) -> object:
    response_text = response_body.decode("utf-8", errors="replace")
    if "\ufffd" in response_text:
        logger.warning("whisper-server JSON output contains invalid UTF-8 bytes")
    return json.loads(response_text)


def _load_transcript_from_verbose_json(payload: object) -> str:
    if not isinstance(payload, Mapping):
        return ""
    payload = cast(Mapping[str, object], payload)
    transcription = payload.get("transcription")
    if not isinstance(transcription, list):
        text = payload.get("text")
        return text.strip() if isinstance(text, str) else ""
    parts: list[str] = []
    for item in transcription:
        if not isinstance(item, Mapping):
            continue
        item = cast(Mapping[str, object], item)
        text = item.get("text")
        if isinstance(text, str):
            normalized = text.strip()
            if normalized:
                parts.append(normalized)
    return " ".join(parts).strip()


def _pcm_rms_level(pcm_bytes: bytes) -> float:
    if len(pcm_bytes) < 2:
        return 0.0
    sample_count = len(pcm_bytes) // 2
    total = 0.0
    for index in range(0, sample_count * 2, 2):
        sample = int.from_bytes(pcm_bytes[index : index + 2], byteorder="little", signed=True)
        total += float(sample * sample)
    return math.sqrt(total / sample_count)


def _wrap_pcm_as_wav(
    pcm_bytes: bytes,
    *,
    sample_rate_hz: int,
    channels: int,
    sample_width: int,
) -> bytes:
    import io
    import wave

    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav_fp:
            wav_fp.setnchannels(channels)
            wav_fp.setsampwidth(sample_width)
            wav_fp.setframerate(sample_rate_hz)
            wav_fp.writeframes(pcm_bytes)
        return buffer.getvalue()


def _encode_multipart_formdata(
    *,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = f"----stackchan-{uuid.uuid4().hex}"
    boundary_bytes = boundary.encode("ascii")
    lines: list[bytes] = []

    for key, value in fields.items():
        lines.extend(
            [
                b"--" + boundary_bytes,
                f'Content-Disposition: form-data; name="{key}"'.encode("utf-8"),
                b"",
                value.encode("utf-8"),
            ]
        )

    for field_name, (filename, content, content_type) in files.items():
        guessed_type = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        lines.extend(
            [
                b"--" + boundary_bytes,
                (
                    f'Content-Disposition: form-data; name="{field_name}"; filename="{Path(filename).name}"'
                ).encode("utf-8"),
                f"Content-Type: {guessed_type}".encode("utf-8"),
                b"",
                content,
            ]
        )

    lines.append(b"--" + boundary_bytes + b"--")
    lines.append(b"")
    body = b"\r\n".join(lines)
    return body, f"multipart/form-data; boundary={boundary}"


__all__ = ["WhisperServerSpeechToText"]
