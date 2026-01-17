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
