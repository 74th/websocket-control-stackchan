from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

from ..speech_recognition.whisper_server import WhisperServerSpeechToText
from .server_side import ServerSideWakeWordDetector


class _CreateServerSideWakeWordDetectorEnv(BaseSettings):
    use_server_side_wwd_whisper_server: bool = Field(
        default=False,
        validation_alias="USE_SERVER_SIDE_WWD_WHISPER_SERVER",
    )

    class Config:
        env_prefix = ""


def create_server_side_wake_word_detector() -> ServerSideWakeWordDetector | None:
    env = _CreateServerSideWakeWordDetectorEnv()
    if not env.use_server_side_wwd_whisper_server:
        return None

    return ServerSideWakeWordDetector(recognizer=WhisperServerSpeechToText())


__all__ = ["create_server_side_wake_word_detector"]
