from __future__ import annotations

from ..types import SpeechRecognizer
from .google_cloud import GoogleCloudSpeechToText
from .whisper_cpp import WhisperCppSpeechToText
from .whisper_server import WhisperServerSpeechToText


def create_speech_recognizer() -> SpeechRecognizer:
    return GoogleCloudSpeechToText()


__all__ = [
    "GoogleCloudSpeechToText",
    "WhisperCppSpeechToText",
    "WhisperServerSpeechToText",
    "create_speech_recognizer",
]
