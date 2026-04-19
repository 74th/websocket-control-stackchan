// Protocol definitions shared between CoreS3 firmware and other components
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "../lib/generated_protobuf/websocket-message.pb.h"

// Internal compatibility metadata for message routing after protobuf decode.
// This is no longer sent on the wire directly.

enum class MessageKind : uint8_t
{
	AudioPcm = 1, // uplink PCM16LE stream (client -> server)
	AudioWav = 2, // downlink WAV bytes (server -> client)
	StateCmd = 3, // state transition command (server -> client)
	WakeWordEvt = 4, // wake word event (client -> server)
	StateEvt = 5, // current state event (client -> server)
	SpeakDoneEvt = 6, // speaking completed event (client -> server)
	ServoCmd = 7, // servo command sequence (server -> client)
	ServoDoneEvt = 8, // servo sequence completed event (client -> server)
};

enum class MessageType : uint8_t
{
	START = 1,
	DATA = 2,
	END = 3,
};

struct __attribute__((packed)) WsHeader
{
	uint8_t kind;        // MessageKind
	uint8_t messageType; // MessageType
	uint8_t reserved;    // 0 (flags/reserved)
	uint32_t seq;        // sequence number
	uint32_t payloadBytes; // bytes following the header
};

// payload for kind=StateCmd, messageType=DATA
// 1 byte: target state id (matches StateMachine::State)
enum class RemoteState : uint8_t
{
	Idle = 0,
	Listening = 1,
	Thinking = 2,
	Speaking = 3,
};

// payload for kind=ServoCmd, messageType=DATA
// <uint8_t command_count><commands...>
//   command op=Sleep: <uint8_t op><int16_t duration_ms>
//   command op=MoveX/Y: <uint8_t op><int8_t angle><int16_t duration_ms>
enum class ServoCommandOp : uint8_t
{
	Sleep = 0,
	MoveX = 1,
	MoveY = 2,
};

constexpr size_t kProtoAudioChunkMaxBytes = 4096;
constexpr size_t kProtoServoCommandMaxCount = 255;
constexpr size_t kMaxEncodedWebSocketMessageBytes = stackchan_websocket_v1_WebSocketMessage_size;

stackchan_websocket_v1_MessageKind toProtoMessageKind(MessageKind kind);
stackchan_websocket_v1_MessageType toProtoMessageType(MessageType type);
stackchan_websocket_v1_StackchanState toProtoState(RemoteState state);
stackchan_websocket_v1_ServoOperation toProtoServoOperation(ServoCommandOp op);

RemoteState fromProtoState(stackchan_websocket_v1_StackchanState state);
ServoCommandOp fromProtoServoOperation(stackchan_websocket_v1_ServoOperation op);

bool setProtoAudioChunk(
	stackchan_websocket_v1_AudioChunk &chunk,
	const uint8_t *data,
	size_t data_len);
const uint8_t *getProtoAudioChunkBytes(const stackchan_websocket_v1_AudioChunk &chunk);
size_t getProtoAudioChunkSize(const stackchan_websocket_v1_AudioChunk &chunk);

bool encodeWebSocketMessage(
	const stackchan_websocket_v1_WebSocketMessage &message,
	std::vector<uint8_t> &encoded);
bool decodeWebSocketMessage(
	const uint8_t *data,
	size_t data_len,
	stackchan_websocket_v1_WebSocketMessage &message);
