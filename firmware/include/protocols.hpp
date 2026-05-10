// Protocol definitions shared between CoreS3 firmware and other components
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "../lib/generated_protobuf/websocket-message.pb.h"

constexpr size_t kProtoAudioChunkMaxBytes = 4096;
constexpr size_t kProtoFileChunkMaxBytes = 4096;
constexpr size_t kProtoServoCommandMaxCount = 255;
constexpr size_t kMaxEncodedWebSocketMessageBytes = stackchan_websocket_v1_WebSocketMessage_size;

bool setProtoAudioChunk(
	stackchan_websocket_v1_AudioChunk &chunk,
	const uint8_t *data,
	size_t data_len);
const uint8_t *getProtoAudioChunkBytes(const stackchan_websocket_v1_AudioChunk &chunk);
size_t getProtoAudioChunkSize(const stackchan_websocket_v1_AudioChunk &chunk);

bool setProtoFileChunk(
	stackchan_websocket_v1_FileChunk &chunk,
	const uint8_t *data,
	size_t data_len);
const uint8_t *getProtoFileChunkBytes(const stackchan_websocket_v1_FileChunk &chunk);
size_t getProtoFileChunkSize(const stackchan_websocket_v1_FileChunk &chunk);

bool encodeWebSocketMessage(
	const stackchan_websocket_v1_WebSocketMessage &message,
	std::vector<uint8_t> &encoded);
bool decodeWebSocketMessage(
	const uint8_t *data,
	size_t data_len,
	stackchan_websocket_v1_WebSocketMessage &message);
