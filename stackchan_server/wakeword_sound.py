from __future__ import annotations

import os
import sys
import wave
from array import array
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path

DEFAULT_WAKE_WORD_SOUND_FILE_ID = "wakeword-detected-sound"
DEFAULT_WAKE_WORD_SOUND_CONTENT_TYPE = "audio/pcm"
WAKEWORD_SOUND_PATH_ENV_VAR = "STACKCHAN_WAKEWORD_SOUND_PATH"
WAKEWORD_SOUND_TARGET_SAMPLE_RATE = 24000
WAKEWORD_SOUND_TARGET_CHANNELS = 1
WAKEWORD_SOUND_PREROLL_MS = 40
WAKEWORD_SOUND_POSTROLL_MS = 180
WAKEWORD_SOUND_MIN_DURATION_MS = 700

logger = getLogger(__name__)


@dataclass(frozen=True)
class WakeWordSound:
    file_id: str
    content_type: str
    payload: bytes
    sample_rate: int
    channels: int


def _decode_pcm16le(payload: bytes) -> array[int]:
    samples = array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def _encode_pcm16le(samples: array[int]) -> bytes:
    encoded = array("h", samples)
    if sys.byteorder != "little":
        encoded.byteswap()
    return encoded.tobytes()


def _clamp_pcm16(value: float) -> int:
    return max(-32768, min(32767, int(round(value))))


def _pcm16_silence(sample_count: int) -> array[int]:
    if sample_count <= 0:
        return array("h")
    return array("h", [0]) * sample_count


def _mix_to_mono(samples: array[int], channels: int) -> array[int]:
    if channels <= 1:
        return array("h", samples)

    mono_samples = array("h")
    frame_count = len(samples) // channels
    for frame_index in range(frame_count):
        base = frame_index * channels
        mixed = sum(samples[base + channel_index] for channel_index in range(channels)) / channels
        mono_samples.append(_clamp_pcm16(mixed))
    return mono_samples


def _resample_mono_pcm16(samples: array[int], src_rate: int, dst_rate: int) -> array[int]:
    if src_rate == dst_rate or len(samples) <= 1:
        return array("h", samples)

    dst_length = max(1, round(len(samples) * dst_rate / src_rate))
    resampled = array("h")
    for dst_index in range(dst_length):
        src_position = dst_index * src_rate / dst_rate
        left_index = int(src_position)
        if left_index >= len(samples) - 1:
            resampled.append(samples[-1])
            continue

        right_index = left_index + 1
        fraction = src_position - left_index
        interpolated = samples[left_index] + (samples[right_index] - samples[left_index]) * fraction
        resampled.append(_clamp_pcm16(interpolated))
    return resampled


def _normalize_pcm16_payload(payload: bytes, sample_rate: int, channels: int) -> tuple[bytes, int, int]:
    samples = _decode_pcm16le(payload)
    mono_samples = _mix_to_mono(samples, channels)
    normalized_samples = _resample_mono_pcm16(
        mono_samples,
        sample_rate,
        WAKEWORD_SOUND_TARGET_SAMPLE_RATE,
    )
    return (
        _encode_pcm16le(normalized_samples),
        WAKEWORD_SOUND_TARGET_SAMPLE_RATE,
        WAKEWORD_SOUND_TARGET_CHANNELS,
    )


def _pad_pcm16_for_short_playback(payload: bytes, sample_rate: int) -> bytes:
    samples = _decode_pcm16le(payload)
    preroll_samples = round(sample_rate * WAKEWORD_SOUND_PREROLL_MS / 1000)
    postroll_samples = round(sample_rate * WAKEWORD_SOUND_POSTROLL_MS / 1000)
    min_duration_samples = round(sample_rate * WAKEWORD_SOUND_MIN_DURATION_MS / 1000)

    padded = _pcm16_silence(preroll_samples)
    padded.extend(samples)
    padded.extend(_pcm16_silence(postroll_samples))

    if len(padded) < min_duration_samples:
        padded.extend(_pcm16_silence(min_duration_samples - len(padded)))

    return _encode_pcm16le(padded)


def load_wake_word_detected_sound_from_env() -> WakeWordSound | None:
    raw_path = os.getenv(WAKEWORD_SOUND_PATH_ENV_VAR, "").strip()
    if not raw_path:
        logger.info(
            "Wake-word sound WAV path is not configured: env=%s",
            WAKEWORD_SOUND_PATH_ENV_VAR,
        )
        return None

    wav_path = Path(raw_path).expanduser()
    if not wav_path.is_absolute():
        wav_path = Path.cwd() / wav_path

    resolved_path = wav_path.resolve()
    logger.info("Loading wake-word sound WAV from %s", resolved_path)
    if not resolved_path.is_file():
        raise FileNotFoundError(
            f"wake word sound wav file not found: {resolved_path}"
        )

    with wave.open(str(resolved_path), "rb") as wav_fp:
        channels = wav_fp.getnchannels()
        sample_width = wav_fp.getsampwidth()
        sample_rate = wav_fp.getframerate()
        payload = wav_fp.readframes(wav_fp.getnframes())

    if sample_width != 2:
        raise ValueError(
            "wake word notification sound wav must be 16-bit PCM"
        )
    if sample_rate <= 0:
        raise ValueError("wake word notification sound wav has invalid sample rate")
    if channels <= 0:
        raise ValueError("wake word notification sound wav has invalid channels")
    if not payload:
        raise ValueError("wake word notification sound wav is empty")

    normalized_payload, normalized_sample_rate, normalized_channels = _normalize_pcm16_payload(
        payload,
        sample_rate,
        channels,
    )
    playback_ready_payload = _pad_pcm16_for_short_playback(
        normalized_payload,
        normalized_sample_rate,
    )

    logger.info(
        "Loaded wake-word sound WAV path=%s source_sample_rate=%d source_channels=%d source_bytes=%d normalized_sample_rate=%d normalized_channels=%d normalized_bytes=%d playback_ready_bytes=%d preroll_ms=%d postroll_ms=%d min_duration_ms=%d",
        resolved_path,
        sample_rate,
        channels,
        len(payload),
        normalized_sample_rate,
        normalized_channels,
        len(normalized_payload),
        len(playback_ready_payload),
        WAKEWORD_SOUND_PREROLL_MS,
        WAKEWORD_SOUND_POSTROLL_MS,
        WAKEWORD_SOUND_MIN_DURATION_MS,
    )

    return WakeWordSound(
        file_id=DEFAULT_WAKE_WORD_SOUND_FILE_ID,
        content_type=DEFAULT_WAKE_WORD_SOUND_CONTENT_TYPE,
        payload=playback_ready_payload,
        sample_rate=normalized_sample_rate,
        channels=normalized_channels,
    )


__all__ = [
    "DEFAULT_WAKE_WORD_SOUND_CONTENT_TYPE",
    "DEFAULT_WAKE_WORD_SOUND_FILE_ID",
    "WAKEWORD_SOUND_PATH_ENV_VAR",
    "WAKEWORD_SOUND_MIN_DURATION_MS",
    "WAKEWORD_SOUND_POSTROLL_MS",
    "WAKEWORD_SOUND_PREROLL_MS",
    "WakeWordSound",
    "load_wake_word_detected_sound_from_env",
]
