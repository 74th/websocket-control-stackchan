from __future__ import annotations

from ..types import SpeechSynthesizer
from .google_cloud import GoogleCloudTextToSpeech
from .voicevox import VoiceVoxSpeechSynthesizer


def create_speech_synthesizer() -> SpeechSynthesizer:
    return VoiceVoxSpeechSynthesizer()


__all__ = ["GoogleCloudTextToSpeech", "VoiceVoxSpeechSynthesizer", "create_speech_synthesizer"]
