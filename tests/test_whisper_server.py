from __future__ import annotations

import unittest

from stackchan_server.speech_recognition.whisper_server import (
    _load_json_response_bytes,
    _load_transcript_from_verbose_json,
)


class WhisperServerJsonTests(unittest.TestCase):
    def test_load_json_response_bytes_replaces_invalid_utf8(self) -> None:
        payload = _load_json_response_bytes(b'{"transcription":[{"text":"\xe6\x90"},{"text":"ok"}]}')

        self.assertEqual(payload, {"transcription": [{"text": "�"}, {"text": "ok"}]})

    def test_load_transcript_from_verbose_json_with_replacement_char(self) -> None:
        payload = {
            "transcription": [
                {"text": "�"},
                {"text": "ok"},
            ]
        }

        transcript = _load_transcript_from_verbose_json(payload)

        self.assertEqual(transcript, "� ok")


if __name__ == "__main__":
    unittest.main()
