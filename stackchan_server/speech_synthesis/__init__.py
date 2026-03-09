from __future__ import annotations

from ..types import SpeechSynthesizer
from .voicevox import VoiceVoxSpeechSynthesizer


def create_speech_synthesizer() -> SpeechSynthesizer:
    return VoiceVoxSpeechSynthesizer()


__all__ = ["VoiceVoxSpeechSynthesizer", "create_speech_synthesizer"]
