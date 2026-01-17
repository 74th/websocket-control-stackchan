// Protocol definitions shared between CoreS3 firmware and other components
#pragma once

#include <cstdint>

// WebSocket audio protocol (PCM1)
// Header layout (little-endian):
//  - kind: 4 bytes ASCII magic "PCM1"
//  - messageType: 1 = START, 2 = DATA, 3 = END
//  - reserved: 1 byte (0)
//  - seq: uint16 (sequence number)
//  - sampleRate: uint32
//  - channels: uint16
//  - payloadBytes: uint16 (bytes of PCM16LE following header)

enum class MessageType : uint8_t
{
	START = 1,
	DATA = 2,
	END = 3,
};

struct __attribute__((packed)) WsAudioHeader
{
	char kind[4];        // "PCM1"
	uint8_t messageType; // MessageType
	uint8_t reserved;    // 0
	uint16_t seq;        // sequence number
	uint32_t sampleRate; // LE
	uint16_t channels;   // 1
	uint16_t payloadBytes; // PCM payload bytes following the header
};
