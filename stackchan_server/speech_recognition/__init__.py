from __future__ import annotations

import importlib
import os
from typing import cast

from ..types import SpeechRecognizer
from .google_cloud import GoogleCloudSpeechToText

_DEFAULT_RECOGNIZER = "google_cloud"


def create_speech_recognizer() -> SpeechRecognizer:
    recognizer_name = os.getenv("STACKCHAN_SPEECH_RECOGNIZER", _DEFAULT_RECOGNIZER)

    if recognizer_name == "google_cloud":
        return GoogleCloudSpeechToText()

    module_name, separator, attr_name = recognizer_name.partition(":")
    if not separator:
        raise ValueError(
            "STACKCHAN_SPEECH_RECOGNIZER must be 'google_cloud' or '<module>:<factory_or_class>'"
        )

    module = importlib.import_module(module_name)
    target = getattr(module, attr_name)
    instance = target() if callable(target) else target
    return cast(SpeechRecognizer, instance)


__all__ = ["GoogleCloudSpeechToText", "create_speech_recognizer"]
