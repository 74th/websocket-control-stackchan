from __future__ import annotations

from ..types import SpeechRecognizer
from .google_cloud import GoogleCloudSpeechToText
from .whisper_cpp import WhisperCppSpeechToText


def create_speech_recognizer() -> SpeechRecognizer:
    return GoogleCloudSpeechToText()


__all__ = ["GoogleCloudSpeechToText", "WhisperCppSpeechToText", "create_speech_recognizer"]
