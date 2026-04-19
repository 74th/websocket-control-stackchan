#include "../include/protocols.hpp"

#include <cstring>

#include <pb_decode.h>
#include <pb_encode.h>

stackchan_websocket_v1_MessageKind toProtoMessageKind(MessageKind kind)
{
	switch (kind)
	{
	case MessageKind::AudioPcm:
		return stackchan_websocket_v1_MessageKind_MESSAGE_KIND_AUDIO_PCM;
	case MessageKind::AudioWav:
		return stackchan_websocket_v1_MessageKind_MESSAGE_KIND_AUDIO_WAV;
	case MessageKind::StateCmd:
		return stackchan_websocket_v1_MessageKind_MESSAGE_KIND_STATE_CMD;
	case MessageKind::WakeWordEvt:
		return stackchan_websocket_v1_MessageKind_MESSAGE_KIND_WAKE_WORD_EVT;
	case MessageKind::StateEvt:
		return stackchan_websocket_v1_MessageKind_MESSAGE_KIND_STATE_EVT;
	case MessageKind::SpeakDoneEvt:
		return stackchan_websocket_v1_MessageKind_MESSAGE_KIND_SPEAK_DONE_EVT;
	case MessageKind::ServoCmd:
		return stackchan_websocket_v1_MessageKind_MESSAGE_KIND_SERVO_CMD;
	case MessageKind::ServoDoneEvt:
		return stackchan_websocket_v1_MessageKind_MESSAGE_KIND_SERVO_DONE_EVT;
	default:
		return stackchan_websocket_v1_MessageKind_MESSAGE_KIND_UNSPECIFIED;
	}
}

stackchan_websocket_v1_MessageType toProtoMessageType(MessageType type)
{
	switch (type)
	{
	case MessageType::START:
		return stackchan_websocket_v1_MessageType_MESSAGE_TYPE_START;
	case MessageType::DATA:
		return stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA;
	case MessageType::END:
		return stackchan_websocket_v1_MessageType_MESSAGE_TYPE_END;
	default:
		return stackchan_websocket_v1_MessageType_MESSAGE_TYPE_UNSPECIFIED;
	}
}

stackchan_websocket_v1_StackchanState toProtoState(RemoteState state)
{
	switch (state)
	{
	case RemoteState::Idle:
		return stackchan_websocket_v1_StackchanState_STACKCHAN_STATE_IDLE;
	case RemoteState::Listening:
		return stackchan_websocket_v1_StackchanState_STACKCHAN_STATE_LISTENING;
	case RemoteState::Thinking:
		return stackchan_websocket_v1_StackchanState_STACKCHAN_STATE_THINKING;
	case RemoteState::Speaking:
		return stackchan_websocket_v1_StackchanState_STACKCHAN_STATE_SPEAKING;
	default:
		return stackchan_websocket_v1_StackchanState_STACKCHAN_STATE_IDLE;
	}
}

stackchan_websocket_v1_ServoOperation toProtoServoOperation(ServoCommandOp op)
{
	switch (op)
	{
	case ServoCommandOp::Sleep:
		return stackchan_websocket_v1_ServoOperation_SERVO_OPERATION_SLEEP;
	case ServoCommandOp::MoveX:
		return stackchan_websocket_v1_ServoOperation_SERVO_OPERATION_MOVE_X;
	case ServoCommandOp::MoveY:
		return stackchan_websocket_v1_ServoOperation_SERVO_OPERATION_MOVE_Y;
	default:
		return stackchan_websocket_v1_ServoOperation_SERVO_OPERATION_SLEEP;
	}
}

RemoteState fromProtoState(stackchan_websocket_v1_StackchanState state)
{
	switch (state)
	{
	case stackchan_websocket_v1_StackchanState_STACKCHAN_STATE_IDLE:
		return RemoteState::Idle;
	case stackchan_websocket_v1_StackchanState_STACKCHAN_STATE_LISTENING:
		return RemoteState::Listening;
	case stackchan_websocket_v1_StackchanState_STACKCHAN_STATE_THINKING:
		return RemoteState::Thinking;
	case stackchan_websocket_v1_StackchanState_STACKCHAN_STATE_SPEAKING:
		return RemoteState::Speaking;
	default:
		return RemoteState::Idle;
	}
}

ServoCommandOp fromProtoServoOperation(stackchan_websocket_v1_ServoOperation op)
{
	switch (op)
	{
	case stackchan_websocket_v1_ServoOperation_SERVO_OPERATION_SLEEP:
		return ServoCommandOp::Sleep;
	case stackchan_websocket_v1_ServoOperation_SERVO_OPERATION_MOVE_X:
		return ServoCommandOp::MoveX;
	case stackchan_websocket_v1_ServoOperation_SERVO_OPERATION_MOVE_Y:
		return ServoCommandOp::MoveY;
	default:
		return ServoCommandOp::Sleep;
	}
}

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
