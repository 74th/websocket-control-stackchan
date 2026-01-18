from logging import StreamHandler, getLogger
# from __future__ import annotations
from vvclient import Client as VVClient

import asyncio
import struct
import wave
import io
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from google.cloud import speech

app = FastAPI(title="CoreS3 PCM receiver")
sst_client = speech.SpeechClient()

logger = getLogger(__name__)
logger.addHandler(StreamHandler())
logger.setLevel("DEBUG")

BASE_DIR = Path(__file__).resolve().parent
RECORDINGS_DIR = BASE_DIR / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

WS_HEADER_FMT = "<BBBHH"  # kind, msg_type, reserved, seq, payload_bytes
WS_HEADER_SIZE = struct.calcsize(WS_HEADER_FMT)
WS_KIND_PCM = 1
WS_KIND_WAV = 2
WS_MSG_START = 1
WS_MSG_DATA = 2
WS_MSG_END = 3

SAMPLE_RATE_HZ = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes

DOWN_WAV_CHUNK = 4096  # bytes per WebSocket frame for synthesized audio (raw PCM)
DOWN_SEGMENT_MILLIS = 2000  # duration of a single START-DATA-END segment in milliseconds
DOWN_SEGMENT_STAGGER_MILLIS = DOWN_SEGMENT_MILLIS // 2  # half interval for the second segment start

def create_voicevox_client() -> VVClient:
    return VVClient(base_uri="http://localhost:50021")


def _ulaw_byte_to_linear(sample: int) -> int:
    """Convert a single μ-law byte to 16-bit PCM (int).

    Kept for compatibility if we ever need to accept μ-law again.
    """

    u_val = (~sample) & 0xFF
    t = ((u_val & 0x0F) << 3) + 0x84
    t <<= (u_val & 0x70) >> 4
    if u_val & 0x80:
        return 0x84 - t
    return t - 0x84


def mulaw_to_pcm16(payload: bytes) -> bytes:
    out = bytearray(len(payload) * 2)
    for i, b in enumerate(payload):
        sample = _ulaw_byte_to_linear(b)
        struct.pack_into("<h", out, i * 2, sample)
    return bytes(out)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/audio")
async def websocket_audio(ws: WebSocket):
    await ws.accept()
    pcm_buffer = bytearray()
    streaming = False
    down_seq = 0
    try:
        while True:
            message = await ws.receive_bytes()
            if len(message) < WS_HEADER_SIZE:
                await ws.close(code=1003, reason="header too short")
                return

            kind, msg_type, _reserved, _seq, payload_bytes = struct.unpack(
                WS_HEADER_FMT, message[:WS_HEADER_SIZE]
            )
            if kind != WS_KIND_PCM:
                await ws.close(code=1003, reason="unsupported kind")
                return

            payload = message[WS_HEADER_SIZE:]
            if payload_bytes != len(payload):
                await ws.close(code=1003, reason="payload length mismatch")
                return

            if msg_type == WS_MSG_START:
                logger.info("Received START, kind=%d", kind)
                pcm_buffer = bytearray()
                streaming = True
                continue

            if msg_type == WS_MSG_DATA:
                logger.info("Received DATA, kind=%d, payload_bytes=%d", kind, payload_bytes)
                if not streaming:
                    await ws.close(code=1003, reason="data received before start")
                    return
                if payload_bytes % (SAMPLE_WIDTH * CHANNELS) != 0:
                    await ws.close(code=1003, reason="invalid pcm chunk length")
                    return
                pcm_buffer.extend(payload)
                continue

            if msg_type == WS_MSG_END:
                logger.info("Received END, kind=%d, payload_bytes=%d", kind, payload_bytes)
                if not streaming:
                    await ws.close(code=1003, reason="end received before start")
                    return
                if payload_bytes % (SAMPLE_WIDTH * CHANNELS) != 0:
                    await ws.close(code=1003, reason="invalid pcm tail length")
                    return
                pcm_buffer.extend(payload)

                if len(pcm_buffer) == 0 or len(pcm_buffer) % (SAMPLE_WIDTH * CHANNELS) != 0:
                    await ws.close(code=1003, reason="invalid accumulated pcm length")
                    return

                frames = len(pcm_buffer) // (SAMPLE_WIDTH * CHANNELS)
                duration_seconds = frames / float(SAMPLE_RATE_HZ)

                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
                filename = f"rec_ws_{timestamp}.wav"
                filepath = RECORDINGS_DIR / filename

                with wave.open(str(filepath), "wb") as wav_fp:
                    wav_fp.setnchannels(CHANNELS)
                    wav_fp.setsampwidth(SAMPLE_WIDTH)
                    wav_fp.setframerate(SAMPLE_RATE_HZ)
                    wav_fp.writeframes(pcm_buffer)

                await ws.send_json(
                    {
                        "text": f"Saved as {filename}",
                        "sample_rate": SAMPLE_RATE_HZ,
                        "frames": frames,
                        "channels": CHANNELS,
                        "duration_seconds": round(duration_seconds, 3),
                        "path": f"recordings/{filename}",
                    }
                )

                logger.info("Saved WAV: %s", filename)

                audio = speech.RecognitionAudio(content=bytes(pcm_buffer))
                config = speech.RecognitionConfig(
                    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                    sample_rate_hertz=SAMPLE_RATE_HZ,
                    language_code="ja-JP",
                )
                response = sst_client.recognize(config=config, audio=audio)

                transcript = ""
                for result in response.results:
                    logger.info(f"Transcript: {result.alternatives[0].transcript}")
                    transcript += result.alternatives[0].transcript

                streaming = False
                pcm_buffer = bytearray()

                voice_text = transcript
                if not transcript:
                    voice_text = "音声を認識できませんでした。"

                # VOICEVOX で合成した音声を CoreS3 へ返送（分割送信）
                try:
                    voice_text = "おはようございます、今日の体調はいかがでしょうか？ 今日の東京は晴れて、とても乾燥して寒い日になりそうです。お出かけの時は暖かくしなさいね。今日こそはジムに行きましょう。"
                    async with create_voicevox_client() as client:
                        audio_query = await client.create_audio_query(voice_text, speaker=29)
                        wav_bytes = await audio_query.synthesis(speaker=29)

                    # Extract raw PCM and meta from WAV
                    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                        pcm_bytes = wf.readframes(wf.getnframes())
                        tts_sample_rate = wf.getframerate()
                        tts_channels = wf.getnchannels()
                        tts_sample_width = wf.getsampwidth()

                    if tts_sample_width != SAMPLE_WIDTH:
                        await ws.send_json({"error": f"unsupported sample width {tts_sample_width}"})
                        continue

                    logger.info(
                        "VOICEVOX synthesis succeeded, sending back RAW PCM sr=%d ch=%d bytes=%d",
                        tts_sample_rate,
                        tts_channels,
                        len(pcm_bytes),
                    )

                    bytes_per_second = tts_sample_rate * tts_channels * tts_sample_width
                    segment_bytes = int(bytes_per_second * (DOWN_SEGMENT_MILLIS / 1000))

                    if segment_bytes <= 0:
                        await ws.send_json({"error": "invalid segment size computed"})
                        continue

                    segments: list[bytes] = []
                    offset = 0
                    total = len(pcm_bytes)
                    while offset < total:
                        segments.append(pcm_bytes[offset : offset + segment_bytes])
                        offset += segment_bytes

                    async def send_segment(segment_pcm: bytes, seq: int) -> int:
                        logger.info("Sending segment bytes=%d", len(segment_pcm))
                        start_payload = struct.pack("<IH", tts_sample_rate, tts_channels)
                        start_hdr = struct.pack(
                            WS_HEADER_FMT,
                            WS_KIND_WAV,
                            WS_MSG_START,
                            0,
                            seq,
                            len(start_payload),
                        )
                        await ws.send_bytes(start_hdr + start_payload)
                        seq += 1

                        seg_offset = 0
                        seg_total = len(segment_pcm)
                        while seg_offset < seg_total:
                            chunk = segment_pcm[seg_offset : seg_offset + DOWN_WAV_CHUNK]
                            data_hdr = struct.pack(
                                WS_HEADER_FMT,
                                WS_KIND_WAV,
                                WS_MSG_DATA,
                                0,
                                seq,
                                len(chunk),
                            )
                            await ws.send_bytes(data_hdr + chunk)
                            seq += 1
                            seg_offset += len(chunk)

                        end_hdr = struct.pack(
                            WS_HEADER_FMT,
                            WS_KIND_WAV,
                            WS_MSG_END,
                            0,
                            seq,
                            0,
                        )
                        await ws.send_bytes(end_hdr)
                        seq += 1
                        return seq

                    loop = asyncio.get_running_loop()
                    base_time = loop.time()

                    for idx, segment in enumerate(segments):
                        if idx == 0:
                            target_ms = 0
                        elif idx == 1:
                            target_ms = DOWN_SEGMENT_STAGGER_MILLIS
                        else:
                            target_ms = DOWN_SEGMENT_STAGGER_MILLIS + (idx - 1) * DOWN_SEGMENT_MILLIS

                        target_time = base_time + target_ms / 1000
                        now = loop.time()
                        if target_time > now:
                            await asyncio.sleep(target_time - now)

                        down_seq = await send_segment(segment, down_seq)

                    logger.info("Sent synthesized RAW PCM back to client via segmented WS streaming protocol")
                except Exception as exc:  # pragma: no cover
                    await ws.send_json({"error": f"voicevox synthesis failed: {exc}"})

                continue

            await ws.close(code=1003, reason="unknown msg type")
            return
    except WebSocketDisconnect:
        return


@app.post("/api/v1/audio")
async def receive_audio(request: Request) -> dict[str, object]:
    codec = request.headers.get("X-Codec", "pcm16le").lower()
    if codec not in {"pcm16", "pcm16le", "mulaw", "ulaw"}:
        raise HTTPException(status_code=400, detail="Unsupported codec. Use pcm16le (preferred) or mulaw.")

    sample_rate_raw = request.headers.get("X-Sample-Rate", "16000")
    try:
        sample_rate = int(sample_rate_raw)
        if sample_rate <= 0:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Sample-Rate must be a positive integer.")

    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail="Request body is empty.")

    try:
        if codec in {"pcm16", "pcm16le"}:
            if len(payload) % 2 != 0:
                raise HTTPException(status_code=400, detail="PCM16 payload size must be even.")
            pcm = payload
        else:
            pcm = mulaw_to_pcm16(payload)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=f"Failed to decode audio payload: {exc}")

    frames = len(pcm) // 2
    duration_seconds = frames / float(sample_rate)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"rec_{timestamp}.wav"
    filepath = RECORDINGS_DIR / filename

    with wave.open(str(filepath), "wb") as wav_fp:
        wav_fp.setnchannels(1)
        wav_fp.setsampwidth(2)
        wav_fp.setframerate(sample_rate)
        wav_fp.writeframes(pcm)

    # Arduino 側は text/audio_mulaw を読む簡易パーサーなので、最低限 text を返す。
    return {
        "text": f"Saved as {filename}",
        "audio_mulaw": "",  # 今回はサーバーで再変換しない
        "sample_rate": sample_rate,
        "frames": frames,
        "duration_seconds": round(duration_seconds, 3),
        "path": f"recordings/{filename}",
    }


def main() -> None:
    import uvicorn

    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
