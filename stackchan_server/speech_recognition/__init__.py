from __future__ import annotations

from ..types import SpeechRecognizer
from .google_cloud import GoogleCloudSpeechToText


def create_speech_recognizer() -> SpeechRecognizer:
    return GoogleCloudSpeechToText()


__all__ = ["GoogleCloudSpeechToText", "create_speech_recognizer"]
