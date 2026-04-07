from pydantic_settings import BaseSettings

from stackchan_server.types import SpeechRecognizer


class _CreateSpeechRecognizerEnv(BaseSettings):
    use_whisper_cli: bool = False
    use_whisper_server: bool = False
    use_google_cloud_stt: bool = True

    class Config:
        env_prefix = "STACKCHAN_"


def create_speech_recognizer() -> SpeechRecognizer:
    es = _CreateSpeechRecognizerEnv()
    if es.use_whisper_cli:
        from .whisper_cli import WhisperCLISpeechToText
        return WhisperCLISpeechToText()

    if es.use_whisper_server:
        from .whisper_server import WhisperServerSpeechToText
        return WhisperServerSpeechToText()

    if es.use_google_cloud_stt:
        from .google_cloud import GoogleCloudSpeechToText
        return GoogleCloudSpeechToText()

    raise ValueError("No speech recognizer configured")
