from __future__ import annotations

from .create import create_speech_synthesizer
from .google_cloud import GoogleCloudTextToSpeech
from .voicevox import VoiceVoxSpeechSynthesizer

__all__ = [
    "GoogleCloudTextToSpeech",
    "VoiceVoxSpeechSynthesizer",
    "create_speech_synthesizer",
]
