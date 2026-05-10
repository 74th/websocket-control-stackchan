#include "../include/protocols.hpp"

#include <cstring>

#include <pb_decode.h>
#include <pb_encode.h>

bool setProtoAudioChunk(
	stackchan_websocket_v1_AudioChunk &chunk,
	const uint8_t *data,
	size_t data_len)
{
	if (data_len > kProtoAudioChunkMaxBytes)
	{
		return false;
	}

	chunk.pcm_bytes.size = static_cast<pb_size_t>(data_len);
	if (data_len > 0 && data != nullptr)
	{
		memcpy(chunk.pcm_bytes.bytes, data, data_len);
	}
	return true;
}

const uint8_t *getProtoAudioChunkBytes(const stackchan_websocket_v1_AudioChunk &chunk)
{
	return chunk.pcm_bytes.bytes;
}

size_t getProtoAudioChunkSize(const stackchan_websocket_v1_AudioChunk &chunk)
{
	return chunk.pcm_bytes.size;
}

bool setProtoFileChunk(
	stackchan_websocket_v1_FileChunk &chunk,
	const uint8_t *data,
	size_t data_len)
{
	if (data_len > kProtoFileChunkMaxBytes)
	{
		return false;
	}

	chunk.chunk_bytes.size = static_cast<pb_size_t>(data_len);
	if (data_len > 0 && data != nullptr)
	{
		memcpy(chunk.chunk_bytes.bytes, data, data_len);
	}
	return true;
}

const uint8_t *getProtoFileChunkBytes(const stackchan_websocket_v1_FileChunk &chunk)
{
	return chunk.chunk_bytes.bytes;
}

size_t getProtoFileChunkSize(const stackchan_websocket_v1_FileChunk &chunk)
{
	return chunk.chunk_bytes.size;
}

bool encodeWebSocketMessage(
	const stackchan_websocket_v1_WebSocketMessage &message,
	std::vector<uint8_t> &encoded)
{
	encoded.assign(kMaxEncodedWebSocketMessageBytes, 0);
	pb_ostream_t stream = pb_ostream_from_buffer(encoded.data(), encoded.size());
	if (!pb_encode(&stream, stackchan_websocket_v1_WebSocketMessage_fields, &message))
	{
		encoded.clear();
		return false;
	}
	encoded.resize(stream.bytes_written);
	return true;
}

bool decodeWebSocketMessage(
	const uint8_t *data,
	size_t data_len,
	stackchan_websocket_v1_WebSocketMessage &message)
{
	message = stackchan_websocket_v1_WebSocketMessage_init_zero;
	pb_istream_t stream = pb_istream_from_buffer(data, data_len);
	return pb_decode(&stream, stackchan_websocket_v1_WebSocketMessage_fields, &message);
}
