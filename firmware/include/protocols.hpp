// Protocol definitions shared between CoreS3 firmware and other components
#pragma once

#include <cstdint>

// WebSocket binary protocol (audio + future kinds)
// Header layout (little-endian, packed):
//  - kind: uint8_t   (message kind)
//  - messageType: uint8_t  (START/DATA/END)
//  - reserved: uint8_t (0, future flags)
//  - seq: uint16 (sequence number)
//  - payloadBytes: uint16 (bytes following the header)

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
	uint16_t seq;        // sequence number
	uint16_t payloadBytes; // bytes following the header
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
