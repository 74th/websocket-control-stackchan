from pydantic_settings import BaseSettings

from stackchan_server.types import SpeechSynthesizer


class SpeechSynthesisEnvSetting(BaseSettings):
    use_voicevox: bool = False
    use_google_cloud_tts: bool = True

    class Config:
        env_prefix = "STACKCHAN_"


def create_speech_synthesizer() -> SpeechSynthesizer:
    es = SpeechSynthesisEnvSetting()
    if es.use_voicevox:
        from .voicevox import VoiceVoxSpeechSynthesizer
        return VoiceVoxSpeechSynthesizer()

    if es.use_google_cloud_tts:
        from .google_cloud import GoogleCloudTextToSpeech
        return GoogleCloudTextToSpeech()

    raise ValueError("No speech synthesizer configured")
