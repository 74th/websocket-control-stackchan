import os
from google.cloud import speech

sst_client = speech.SpeechClient()

def main():
    with open(".log/recordings/output.wav", "rb") as f:
        audio_content = f.read()

    audio = speech.RecognitionAudio(content=audio_content)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code="ja-JP",
    )
    response = sst_client.recognize(config=config, audio=audio)

    for result in response.results:
        print(f"Transcript: {result.alternatives[0].transcript}")

    return response


if __name__ == "__main__":
    main()
