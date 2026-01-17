from logging import StreamHandler, getLogger
# from __future__ import annotations
from vvclient import Client as VVClient

import struct
import wave
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

DOWN_WAV_CHUNK = 4096  # bytes per WebSocket frame for synthesized audio

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
                pcm_buffer = bytearray()
                streaming = True
                continue

            if msg_type == WS_MSG_DATA:
                if not streaming:
                    await ws.close(code=1003, reason="data received before start")
                    return
                if payload_bytes % (SAMPLE_WIDTH * CHANNELS) != 0:
                    await ws.close(code=1003, reason="invalid pcm chunk length")
                    return
                pcm_buffer.extend(payload)
                continue

            if msg_type == WS_MSG_END:
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
                    async with create_voicevox_client() as client:
                        audio_query = await client.create_audio_query(voice_text, speaker=29)
                        wav_bytes = await audio_query.synthesis(speaker=29)
                    logger.info("VOICEVOX synthesis succeeded, sending back WAV")

                    # START (no payload): begin streaming
                    start_hdr = struct.pack(
                        WS_HEADER_FMT,
                        WS_KIND_WAV,
                        WS_MSG_START,
                        0,
                        down_seq,
                        0,
                    )
                    await ws.send_bytes(start_hdr)
                    down_seq += 1

                    # DATA chunks (streaming)
                    offset = 0
                    total = len(wav_bytes)
                    while offset < total:
                        chunk = wav_bytes[offset : offset + DOWN_WAV_CHUNK]
                        data_hdr = struct.pack(
                            WS_HEADER_FMT,
                            WS_KIND_WAV,
                            WS_MSG_DATA,
                            0,
                            down_seq,
                            len(chunk),
                        )
                        await ws.send_bytes(data_hdr + chunk)
                        down_seq += 1
                        offset += len(chunk)

                    # END (no payload)
                    end_hdr = struct.pack(
                        WS_HEADER_FMT,
                        WS_KIND_WAV,
                        WS_MSG_END,
                        0,
                        down_seq,
                        0,
                    )
                    await ws.send_bytes(end_hdr)
                    down_seq += 1

                    logger.info("Sent synthesized WAV back to client via WS streaming protocol")
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
