from __future__ import annotations

import asyncio
import io
import json
import math
import os
import shlex
import shutil
import tempfile
import wave
from logging import getLogger
from pathlib import Path

from ..static import LISTEN_AUDIO_FORMAT, LISTEN_LANGUAGE_CODE
from ..types import SpeechRecognizer

logger = getLogger(__name__)
_DEFAULT_SILENCE_RMS_THRESHOLD = 75.0
_DEFAULT_VAD_THRESHOLD = 0.6
_DEFAULT_VAD_MIN_SPEECH_DURATION_MS = 250
_DEFAULT_VAD_MIN_SILENCE_DURATION_MS = 400
_DEFAULT_VAD_SPEECH_PAD_MS = 30


class WhisperCppSpeechToText(SpeechRecognizer):
    def __init__(
        self,
        *,
        model_path: str | Path,
        cli_path: str = "whisper-cli",
        threads: int | None = None,
        translate: bool = False,
        no_speech_threshold: float = 0.8,
        suppress_non_speech_tokens: bool = True,
        vad_model_path: str | Path | None = None,
        use_vad: bool = True,
        vad_threshold: float = _DEFAULT_VAD_THRESHOLD,
        vad_min_speech_duration_ms: int = _DEFAULT_VAD_MIN_SPEECH_DURATION_MS,
        vad_min_silence_duration_ms: int = _DEFAULT_VAD_MIN_SILENCE_DURATION_MS,
        vad_speech_pad_ms: int = _DEFAULT_VAD_SPEECH_PAD_MS,
        silence_rms_threshold: float = _DEFAULT_SILENCE_RMS_THRESHOLD,
    ) -> None:
        self._model_path = Path(model_path)
        self._cli_path = cli_path
        self._threads = threads
        self._translate = translate
        self._no_speech_threshold = no_speech_threshold
        self._suppress_non_speech_tokens = suppress_non_speech_tokens
        self._vad_model_path = _resolve_vad_model_path(vad_model_path)
        self._use_vad = use_vad
        self._vad_threshold = vad_threshold
        self._vad_min_speech_duration_ms = vad_min_speech_duration_ms
        self._vad_min_silence_duration_ms = vad_min_silence_duration_ms
        self._vad_speech_pad_ms = vad_speech_pad_ms
        self._silence_rms_threshold = silence_rms_threshold

    async def transcribe(self, pcm_bytes: bytes) -> str:
        if not self._model_path.is_file():
            raise FileNotFoundError(f"whisper.cpp model not found: {self._model_path}")
        if _pcm_rms_level(pcm_bytes) < self._silence_rms_threshold:
            logger.info(
                "Skipping whisper.cpp transcription because pcm rms %.2f is below silence threshold %.2f",
                _pcm_rms_level(pcm_bytes),
                self._silence_rms_threshold,
            )
            return ""

        cli_path = shutil.which(self._cli_path)
        if cli_path is None:
            raise FileNotFoundError(f"whisper.cpp CLI not found in PATH: {self._cli_path}")

        language = _normalize_language(LISTEN_LANGUAGE_CODE)
        with tempfile.TemporaryDirectory(prefix="stackchan_whisper_") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            wav_path = temp_dir / "input.wav"
            out_base = temp_dir / "result"
            json_path = out_base.with_suffix(".json")
            _write_wav(
                wav_path,
                pcm_bytes,
                sample_rate_hz=LISTEN_AUDIO_FORMAT.sample_rate_hz,
                channels=LISTEN_AUDIO_FORMAT.channels,
                sample_width=LISTEN_AUDIO_FORMAT.sample_width,
            )

            command = [
                cli_path,
                "-m",
                str(self._model_path),
                "-f",
                str(wav_path),
                "-l",
                language,
                "-nth",
                str(self._no_speech_threshold),
                "-nt",
                "-ojf",
                "-of",
                str(out_base),
            ]
            if self._threads is not None:
                command.extend(["-t", str(self._threads)])
            if self._translate:
                command.append("-tr")
            if self._suppress_non_speech_tokens:
                command.append("-sns")
            if self._use_vad and self._vad_model_path is not None:
                command.extend(
                    [
                        "--vad",
                        "-vm",
                        str(self._vad_model_path),
                        "-vt",
                        str(self._vad_threshold),
                        "-vspd",
                        str(self._vad_min_speech_duration_ms),
                        "-vsd",
                        str(self._vad_min_silence_duration_ms),
                        "-vp",
                        str(self._vad_speech_pad_ms),
                    ]
                )
            command.append("-np")

            logger.info(
                "Running whisper.cpp command: %s",
                shlex.join(command),
            )
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                stderr_text = stderr.decode("utf-8", errors="replace").strip()
                stdout_text = stdout.decode("utf-8", errors="replace").strip()
                raise RuntimeError(
                    "whisper.cpp failed: "
                    f"exit_code={process.returncode} stderr={stderr_text or '<empty>'} "
                    f"stdout={stdout_text or '<empty>'}"
                )

            if not json_path.is_file():
                raise RuntimeError("whisper.cpp did not produce a JSON transcript file")

            transcript = _load_transcript_from_json(json_path)
            if transcript:
                logger.info("whisper.cpp transcript: %s", transcript)
            return transcript


def _normalize_language(language_code: str) -> str:
    if not language_code:
        return "auto"
    return language_code.split("-", 1)[0].lower()


def _normalize_transcript(text: str) -> str:
    return text.strip()


def _load_transcript_from_json(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    transcription = data.get("transcription")
    if not isinstance(transcription, list):
        return ""
    parts: list[str] = []
    for item in transcription:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            normalized = _normalize_transcript(text)
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


def _resolve_vad_model_path(vad_model_path: str | Path | None) -> Path | None:
    if vad_model_path is not None:
        path = Path(vad_model_path)
        return path if path.is_file() else None

    env_path = os.getenv("STACKCHAN_WHISPER_VAD_MODEL")
    if env_path:
        path = Path(env_path)
        if path.is_file():
            return path

    return None


def _write_wav(
    path: Path,
    pcm_bytes: bytes,
    *,
    sample_rate_hz: int,
    channels: int,
    sample_width: int,
) -> None:
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav_fp:
            wav_fp.setnchannels(channels)
            wav_fp.setsampwidth(sample_width)
            wav_fp.setframerate(sample_rate_hz)
            wav_fp.writeframes(pcm_bytes)
        path.write_bytes(buffer.getvalue())


__all__ = ["WhisperCppSpeechToText"]
