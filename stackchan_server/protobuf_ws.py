from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Literal, cast

from .generated_protobuf import websocket_message_pb2 as _ws_pb2

ws_pb2: Any = _ws_pb2

ServoMoveType: type[StrEnum] | None = None
ServoWaitType: type[StrEnum] | None = None
ServoMoveCommand = tuple[Literal["move_x", "move_y"] | StrEnum, int, int]
ServoSleepCommand = tuple[Literal["sleep"] | StrEnum, int]
ServoCommand = ServoMoveCommand | ServoSleepCommand


def _ensure_range(value: int, *, minimum: int, maximum: int, label: str) -> int:
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}: {value}")
    return value


def parse_websocket_message(data: bytes) -> Any:
    message = ws_pb2.WebSocketMessage()
    message.ParseFromString(data)
    return message


def _new_message(kind: int, message_type: int, seq: int) -> Any:
    return ws_pb2.WebSocketMessage(kind=kind, message_type=message_type, seq=seq)


def encode_audio_pcm_start_message(seq: int) -> bytes:
    message = _new_message(
        ws_pb2.MESSAGE_KIND_AUDIO_PCM,
        ws_pb2.MESSAGE_TYPE_START,
        seq,
    )
    message.audio_pcm_start.SetInParent()
    return message.SerializeToString()


def encode_audio_pcm_data_message(seq: int, pcm_bytes: bytes) -> bytes:
    message = _new_message(
        ws_pb2.MESSAGE_KIND_AUDIO_PCM,
        ws_pb2.MESSAGE_TYPE_DATA,
        seq,
    )
    message.audio_pcm_data.pcm_bytes = pcm_bytes
    return message.SerializeToString()


def encode_audio_pcm_end_message(seq: int) -> bytes:
    message = _new_message(
        ws_pb2.MESSAGE_KIND_AUDIO_PCM,
        ws_pb2.MESSAGE_TYPE_END,
        seq,
    )
    message.audio_pcm_end.SetInParent()
    return message.SerializeToString()


def encode_audio_wav_start_message(seq: int, *, sample_rate: int, channels: int) -> bytes:
    message = _new_message(
        ws_pb2.MESSAGE_KIND_AUDIO_WAV,
        ws_pb2.MESSAGE_TYPE_START,
        seq,
    )
    message.audio_wav_start.sample_rate = int(sample_rate)
    message.audio_wav_start.channels = int(channels)
    return message.SerializeToString()


def encode_audio_wav_data_message(seq: int, pcm_bytes: bytes) -> bytes:
    message = _new_message(
        ws_pb2.MESSAGE_KIND_AUDIO_WAV,
        ws_pb2.MESSAGE_TYPE_DATA,
        seq,
    )
    message.audio_wav_data.pcm_bytes = pcm_bytes
    return message.SerializeToString()


def encode_audio_wav_end_message(seq: int) -> bytes:
    message = _new_message(
        ws_pb2.MESSAGE_KIND_AUDIO_WAV,
        ws_pb2.MESSAGE_TYPE_END,
        seq,
    )
    message.audio_wav_end.SetInParent()
    return message.SerializeToString()


def encode_state_command_message(seq: int, state_id: int) -> bytes:
    message = _new_message(
        ws_pb2.MESSAGE_KIND_STATE_CMD,
        ws_pb2.MESSAGE_TYPE_DATA,
        seq,
    )
    message.state_cmd.state = int(state_id)
    return message.SerializeToString()


def encode_servo_command_message(seq: int, commands: Sequence[ServoCommand]) -> bytes:
    normalized = list(commands)
    _ensure_range(len(normalized), minimum=0, maximum=255, label="servo command count")

    message = _new_message(
        ws_pb2.MESSAGE_KIND_SERVO_CMD,
        ws_pb2.MESSAGE_TYPE_DATA,
        seq,
    )

    for index, command in enumerate(normalized):
        encoded = message.servo_cmd.commands.add()
        if len(command) == 2:
            name, raw_duration_ms = cast(ServoSleepCommand, command)
            if str(name) != "sleep":
                raise ValueError(f"unsupported servo command at index {index}: {name}")
            encoded.op = ws_pb2.SERVO_OPERATION_SLEEP
            encoded.duration_ms = _ensure_range(
                int(raw_duration_ms),
                minimum=-32768,
                maximum=32767,
                label="sleep duration",
            )
            continue

        if len(command) == 3:
            name, raw_angle, raw_duration_ms = cast(ServoMoveCommand, command)
            if str(name) not in ("move_x", "move_y"):
                raise ValueError(f"unsupported servo command at index {index}: {name}")
            encoded.op = (
                ws_pb2.SERVO_OPERATION_MOVE_X
                if str(name) == "move_x"
                else ws_pb2.SERVO_OPERATION_MOVE_Y
            )
            encoded.angle = _ensure_range(
                int(raw_angle),
                minimum=-128,
                maximum=127,
                label="servo angle",
            )
            encoded.duration_ms = _ensure_range(
                int(raw_duration_ms),
                minimum=-32768,
                maximum=32767,
                label="servo duration",
            )
            continue

        raise ValueError(f"unsupported servo command at index {index}: {command}")

    return message.SerializeToString()


__all__ = [
    "ServoCommand",
    "encode_audio_pcm_data_message",
    "encode_audio_pcm_end_message",
    "encode_audio_pcm_start_message",
    "encode_audio_wav_data_message",
    "encode_audio_wav_end_message",
    "encode_audio_wav_start_message",
    "encode_servo_command_message",
    "encode_state_command_message",
    "parse_websocket_message",
    "ws_pb2",
]
