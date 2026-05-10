from __future__ import annotations

from pydantic_settings import BaseSettings

from .whisper_server import WhisperServerWakeWordDetector


class _CreateWhisperServerWakeWordDetectorEnv(BaseSettings):
    use_wwd_whisper_server: bool = False

    class Config:
        env_prefix = "STACKCHAN_"


def create_server_side_wake_word_detector() -> WhisperServerWakeWordDetector | None:
    env = _CreateWhisperServerWakeWordDetectorEnv()
    if not env.use_wwd_whisper_server:
        return None

    return WhisperServerWakeWordDetector()


__all__ = ["create_server_side_wake_word_detector"]
