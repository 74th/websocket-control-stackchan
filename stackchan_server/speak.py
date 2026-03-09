from __future__ import annotations

import asyncio
import io
import struct
import wave
from datetime import UTC, datetime
from logging import getLogger
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import WebSocket, WebSocketDisconnect

from .listen import TimeoutError
from .types import AudioFormat, SpeechSynthesizer, StreamingSpeechSynthesizer

logger = getLogger(__name__)


class SpeakHandler:
    def __init__(
        self,
        *,
        websocket: WebSocket,
        ws_header_fmt: str,
        wav_kind: int,
        start_msg_type: int,
        data_msg_type: int,
        end_msg_type: int,
        down_wav_chunk: int,
        down_segment_millis: int,
        down_segment_stagger_millis: int,
        sample_width: int,
        speech_synthesizer: SpeechSynthesizer,
        recordings_dir: Path,
        debug_recording: bool,
    ) -> None:
        self.ws = websocket
        self.ws_header_fmt = ws_header_fmt
        self.wav_kind = wav_kind
        self.start_msg_type = start_msg_type
        self.data_msg_type = data_msg_type
        self.end_msg_type = end_msg_type
        self.down_wav_chunk = down_wav_chunk
        self.down_segment_millis = down_segment_millis
        self.down_segment_stagger_millis = down_segment_stagger_millis
        self.sample_width = sample_width
        self.speech_synthesizer = speech_synthesizer
        self.recordings_dir = recordings_dir
        self.debug_recording = debug_recording

        self._speaking = False
        self._speak_finished_counter = 0

    @property
    def speaking(self) -> bool:
        return self._speaking

    def handle_speak_done_event(self) -> None:
        self._speak_finished_counter += 1
        self._speaking = False
        logger.info("Received speak done event")

    async def speak(
        self,
        text: str,
        *,
        next_seq: Callable[[], int],
        send_state_command: Callable[[int], Awaitable[None]],
        idle_state: int,
        is_closed: Callable[[], bool],
    ) -> None:
        start_counter = self._speak_finished_counter
        await self._start_talking_stream(text, next_seq=next_seq)
        if not self._speaking:
            return
        await self._wait_for_speaking_finished(
            min_counter=start_counter + 1,
            timeout_seconds=120.0,
            is_closed=is_closed,
        )
        if not is_closed():
            await send_state_command(idle_state)

    async def _wait_for_speaking_finished(
        self,
        *,
        min_counter: int,
        timeout_seconds: float | None,
        is_closed: Callable[[], bool],
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = (loop.time() + timeout_seconds) if timeout_seconds else None
        while True:
            if self._speak_finished_counter >= min_counter:
                return
            if is_closed():
                raise WebSocketDisconnect()
            if deadline and loop.time() >= deadline:
                raise TimeoutError("Timed out waiting for speaking finished event")
            await asyncio.sleep(0.05)

    async def _start_talking_stream(self, text: str, *, next_seq: Callable[[], int]) -> None:
        self._speaking = True
        try:
            if isinstance(self.speech_synthesizer, StreamingSpeechSynthesizer):
                await self._start_talking_streaming(
                    text,
                    self.speech_synthesizer,
                    next_seq=next_seq,
                )
                return
            wav_bytes = await self.speech_synthesizer.synthesize(text)
            logger.info("Synthesized wav_bytes=%d text_chars=%d", len(wav_bytes), len(text))
            pcm_bytes, tts_sample_rate, tts_channels, tts_sample_width = self._extract_pcm(wav_bytes)
            logger.info(
                "Synthesized audio sample_rate=%d channels=%d sample_width=%d pcm_bytes=%d",
                tts_sample_rate,
                tts_channels,
                tts_sample_width,
                len(pcm_bytes),
            )
            if len(pcm_bytes) == 0:
                logger.warning("Synthesized audio is empty")
                self._speaking = False
                return

            if tts_sample_width != self.sample_width:
                await self.ws.send_json({"error": f"unsupported sample width {tts_sample_width}"})
                self._speaking = False
                return

            if self.debug_recording:
                filepath, filename = self._save_wav(wav_bytes)
                logger.info("Saved synthesized WAV: %s", filename)
                await self.ws.send_json({"tts_debug_path": f"recordings/{filename}", "tts_debug_bytes": len(wav_bytes)})

            bytes_per_second = tts_sample_rate * tts_channels * tts_sample_width
            segment_bytes = int(bytes_per_second * (self.down_segment_millis / 1000))

            if segment_bytes <= 0:
                await self.ws.send_json({"error": "invalid segment size computed"})
                self._speaking = False
                return

            await self._send_segments(
                pcm_bytes,
                tts_sample_rate,
                tts_channels,
                segment_bytes,
                next_seq=next_seq,
            )
        except Exception as exc:  # pragma: no cover
            self._speaking = False
            logger.exception("Speech synthesis failed")
            await self.ws.send_json({"error": f"speech synthesis failed: {exc}"})

    async def _start_talking_streaming(
        self,
        text: str,
        speech_synthesizer: StreamingSpeechSynthesizer,
        *,
        next_seq: Callable[[], int],
    ) -> None:
        output_format = speech_synthesizer.output_format
        logger.info(
            "Streaming synthesized audio sample_rate=%d channels=%d sample_width=%d",
            output_format.sample_rate_hz,
            output_format.channels,
            output_format.sample_width,
        )
        if output_format.sample_width != self.sample_width:
            await self.ws.send_json({"error": f"unsupported sample width {output_format.sample_width}"})
            self._speaking = False
            return

        bytes_per_second = (
            output_format.sample_rate_hz * output_format.channels * output_format.sample_width
        )
        segment_bytes = int(bytes_per_second * (self.down_segment_millis / 1000))
        if segment_bytes <= 0:
            await self.ws.send_json({"error": "invalid segment size computed"})
            self._speaking = False
            return

        pending = bytearray()
        saved_pcm = bytearray()
        segment_count = 0
        base_time: float | None = None
        async for chunk in speech_synthesizer.synthesize_stream(text):
            pending.extend(chunk)
            if self.debug_recording:
                saved_pcm.extend(chunk)
            while len(pending) >= segment_bytes:
                segment = bytes(pending[:segment_bytes])
                del pending[:segment_bytes]
                base_time = await self._wait_for_segment_slot(segment_count, base_time=base_time)
                await self._send_segment(
                    segment,
                    output_format.sample_rate_hz,
                    output_format.channels,
                    next_seq=next_seq,
                )
                segment_count += 1
        if pending:
            base_time = await self._wait_for_segment_slot(segment_count, base_time=base_time)
            await self._send_segment(
                bytes(pending),
                output_format.sample_rate_hz,
                output_format.channels,
                next_seq=next_seq,
            )
            segment_count += 1
        logger.info("Prepared %d playback segments from streaming TTS", segment_count)

        if self.debug_recording and saved_pcm:
            wav_bytes = self._wrap_pcm_as_wav(bytes(saved_pcm), output_format)
            filepath, filename = self._save_wav(wav_bytes)
            logger.info("Saved synthesized WAV: %s", filename)
            await self.ws.send_json({"tts_debug_path": f"recordings/{filename}", "tts_debug_bytes": len(wav_bytes)})

        if segment_count == 0:
            logger.warning("Synthesized audio is empty")
            self._speaking = False

    def _extract_pcm(self, wav_bytes: bytes) -> tuple[bytes, int, int, int]:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            pcm_bytes = wf.readframes(wf.getnframes())
            tts_sample_rate = wf.getframerate()
            tts_channels = wf.getnchannels()
            tts_sample_width = wf.getsampwidth()
        return pcm_bytes, tts_sample_rate, tts_channels, tts_sample_width

    def _save_wav(self, wav_bytes: bytes) -> tuple[Path, str]:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"tts_ws_{timestamp}.wav"
        filepath = self.recordings_dir / filename
        filepath.write_bytes(wav_bytes)
        return filepath, filename

    def _wrap_pcm_as_wav(self, pcm_bytes: bytes, audio_format: AudioFormat) -> bytes:
        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as wav_fp:
                wav_fp.setnchannels(audio_format.channels)
                wav_fp.setsampwidth(audio_format.sample_width)
                wav_fp.setframerate(audio_format.sample_rate_hz)
                wav_fp.writeframes(pcm_bytes)
            return buffer.getvalue()

    async def _wait_for_segment_slot(self, segment_index: int, *, base_time: float | None) -> float:
        loop = asyncio.get_running_loop()
        if base_time is None:
            return loop.time()

        if segment_index == 0:
            target_ms = 0
        elif segment_index == 1:
            target_ms = self.down_segment_stagger_millis
        else:
            target_ms = self.down_segment_stagger_millis + (segment_index - 1) * self.down_segment_millis

        target_time = base_time + target_ms / 1000
        now = loop.time()
        if target_time > now:
            await asyncio.sleep(target_time - now)
        return base_time

    async def _send_segments(
        self,
        pcm_bytes: bytes,
        tts_sample_rate: int,
        tts_channels: int,
        segment_bytes: int,
        *,
        next_seq: Callable[[], int],
    ) -> None:
        segments: list[bytes] = []
        offset = 0
        total = len(pcm_bytes)
        while offset < total:
            segments.append(pcm_bytes[offset : offset + segment_bytes])
            offset += segment_bytes
        logger.info("Prepared %d playback segments", len(segments))

        loop = asyncio.get_running_loop()
        base_time = loop.time()

        for idx, segment in enumerate(segments):
            if idx == 0:
                target_ms = 0
            elif idx == 1:
                target_ms = self.down_segment_stagger_millis
            else:
                target_ms = self.down_segment_stagger_millis + (idx - 1) * self.down_segment_millis

            target_time = base_time + target_ms / 1000
            now = loop.time()
            if target_time > now:
                await asyncio.sleep(target_time - now)

            await self._send_segment(segment, tts_sample_rate, tts_channels, next_seq=next_seq)

    async def _send_segment(
        self,
        segment_pcm: bytes,
        tts_sample_rate: int,
        tts_channels: int,
        *,
        next_seq: Callable[[], int],
    ) -> None:
        logger.info("Sending segment bytes=%d", len(segment_pcm))
        start_payload = struct.pack("<IH", tts_sample_rate, tts_channels)
        start_hdr = struct.pack(
            self.ws_header_fmt,
            self.wav_kind,
            self.start_msg_type,
            0,
            next_seq(),
            len(start_payload),
        )
        await self.ws.send_bytes(start_hdr + start_payload)

        seg_offset = 0
        seg_total = len(segment_pcm)
        while seg_offset < seg_total:
            chunk = segment_pcm[seg_offset : seg_offset + self.down_wav_chunk]
            data_hdr = struct.pack(
                self.ws_header_fmt,
                self.wav_kind,
                self.data_msg_type,
                0,
                next_seq(),
                len(chunk),
            )
            await self.ws.send_bytes(data_hdr + chunk)
            seg_offset += len(chunk)

        end_hdr = struct.pack(
            self.ws_header_fmt,
            self.wav_kind,
            self.end_msg_type,
            0,
            next_seq(),
            0,
        )
        await self.ws.send_bytes(end_hdr)

__all__ = ["SpeakHandler"]
