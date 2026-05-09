#include "listening.hpp"
#include <algorithm>
#include <cstring>
#include <vector>
#include <cstdlib>

namespace
{
stackchan_websocket_v1_WebSocketMessage g_listening_tx_message = stackchan_websocket_v1_WebSocketMessage_init_zero;
}

Listening::Listening(WebSocketsClient &ws, StateMachine &sm, int sampleRate)
    : ws_(ws), state_(sm), sample_rate_(sampleRate),
      chunk_samples_(static_cast<size_t>(sampleRate) / 8),
      ring_capacity_samples_(static_cast<size_t>(sampleRate) * 2)
{
}

void Listening::init()
{
  if (ring_buffer_)
  {
    heap_caps_free(ring_buffer_);
    ring_buffer_ = nullptr;
  }

  if (ring_buffer_)
  {
    heap_caps_free(ring_buffer_);
    ring_buffer_ = nullptr;
  }
  ring_buffer_ = (int16_t *)heap_caps_malloc(ring_capacity_samples_ * sizeof(int16_t), MALLOC_CAP_8BIT);
  if (ring_buffer_)
  {
    memset(ring_buffer_, 0, ring_capacity_samples_ * sizeof(int16_t));
  }
  ring_write_ = ring_read_ = ring_available_ = 0;
  seq_counter_ = 0;
  streaming_ = false;
}

void Listening::begin()
{
  M5.Mic.begin();
  beginStreamingSession(SessionMode::Speech, true);
}

void Listening::end()
{
  stopStreaming();
  stopMicrophoneOnly();
}

bool Listening::beginWakeWordStreaming()
{
  if (streaming_)
  {
    return session_mode_ == SessionMode::WakeWord;
  }

  M5.Mic.begin();
  return beginStreamingSession(SessionMode::WakeWord, false);
}

void Listening::endWakeWordStreaming()
{
  stopStreaming();
  stopMicrophoneOnly();
}

bool Listening::startStreaming()
{
  return beginStreamingSession(SessionMode::Speech, true);
}

bool Listening::beginStreamingSession(SessionMode mode, bool auto_stop_for_silence)
{
  ring_write_ = ring_read_ = ring_available_ = 0;
  seq_counter_ = 0;
  last_level_ = 0;
  silence_since_ms_ = 0;
  session_mode_ = mode;
  auto_stop_for_silence_ = auto_stop_for_silence;
  streaming_ = true;
  return sendPacket(stackchan_websocket_v1_MessageType_MESSAGE_TYPE_START, nullptr, 0);
}

bool Listening::stopStreaming()
{
  if (!streaming_)
  {
    return true;
  }

  // flush remaining samples before END
  bool ok = true;
  if (ring_available_ > 0)
  {
    const size_t tail_capacity = chunk_samples_;
    std::vector<int16_t> tail_buf(tail_capacity);
    size_t to_send = ring_available_;
    while (to_send > 0)
    {
      size_t chunk = std::min({chunk_samples_, to_send, tail_capacity});
      size_t sent = ringPop(tail_buf.data(), chunk);
      if (!sendPacket(stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA, tail_buf.data(), sent))
      {
        ok = false;
        break;
      }
      to_send -= sent;
    }
  }

  streaming_ = false;
  session_mode_ = SessionMode::Speech;
  auto_stop_for_silence_ = true;
  ok = sendPacket(stackchan_websocket_v1_MessageType_MESSAGE_TYPE_END, nullptr, 0) && ok;
  return ok;
}

void Listening::stopMicrophoneOnly()
{
  session_mode_ = SessionMode::Speech;
  auto_stop_for_silence_ = true;
  M5.Mic.end();
}

void Listening::loop()
{
  if (!streaming_)
  {
    return;
  }

  static int16_t mic_buf[256];
  if (M5.Mic.isEnabled())
  {
    if (M5.Mic.record(mic_buf, mic_read_samples_, sample_rate_))
    {
      ringPush(mic_buf, mic_read_samples_);
      updateLevelStats(mic_buf, mic_read_samples_);
    }
  }

  while (ring_available_ >= chunk_samples_)
  {
    static std::vector<int16_t> send_buf;
    if (send_buf.size() < chunk_samples_)
    {
      send_buf.resize(chunk_samples_);
    }

    size_t got = ringPop(send_buf.data(), chunk_samples_);
    if (!sendPacket(stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA, send_buf.data(), got))
    {
      streaming_ = false;
      log_i("WS send failed (data)");
      if (session_mode_ == SessionMode::Speech)
      {
        state_.setState(StateMachine::Idle);
      }
      else
      {
        stopMicrophoneOnly();
      }
      return;
    }
  }

  // 無音が3秒続いたら終了
  if (auto_stop_for_silence_ && shouldStopForSilence())
  {
    log_i("Auto stop: silence detected (avg=%ld)", static_cast<long>(last_level_));
    if (!stopStreaming())
    {
      log_i("WS send failed (tail/end)");
    }
    state_.setState(StateMachine::Idle);

    // 終了直後のTTS再生でMic/Speakerが競合しないよう、少し待つ
    delay(20);
  }
}

void Listening::updateLevelStats(const int16_t *samples, size_t sampleCount)
{
  if (sampleCount == 0)
  {
    return;
  }

  int64_t sum = 0;
  for (size_t i = 0; i < sampleCount; ++i)
  {
    sum += std::abs(samples[i]);
  }
  last_level_ = static_cast<int32_t>(sum / static_cast<int64_t>(sampleCount));

  uint32_t now = millis();
  if (last_level_ <= kSilenceLevelThreshold)
  {
    if (silence_since_ms_ == 0)
    {
      silence_since_ms_ = now;
    }
  }
  else
  {
    silence_since_ms_ = 0;
  }
}

bool Listening::shouldStopForSilence() const
{
  if (silence_since_ms_ == 0)
  {
    return false;
  }

  if (last_level_ > kSilenceLevelThreshold)
  {
    return false;
  }

  uint32_t elapsed = millis() - silence_since_ms_;
  return elapsed >= kSilenceDurationMs;
}

bool Listening::sendPacket(stackchan_websocket_v1_MessageType type, const int16_t *samples, size_t sampleCount)
{
  if ((WiFi.status() != WL_CONNECTED) || !ws_.isConnected())
  {
    return false;
  }

  auto &message = g_listening_tx_message;
  message = stackchan_websocket_v1_WebSocketMessage_init_zero;
  message.kind = stackchan_websocket_v1_MessageKind_MESSAGE_KIND_AUDIO_PCM;
  message.message_type = type;
  message.seq = seq_counter_++;

  switch (type)
  {
  case stackchan_websocket_v1_MessageType_MESSAGE_TYPE_START:
    message.which_body = stackchan_websocket_v1_WebSocketMessage_audio_pcm_start_tag;
    break;
  case stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA:
    message.which_body = stackchan_websocket_v1_WebSocketMessage_audio_pcm_data_tag;
    if (!setProtoAudioChunk(
            message.body.audio_pcm_data,
            reinterpret_cast<const uint8_t *>(samples),
            sampleCount * sizeof(int16_t)))
    {
      return false;
    }
    break;
  case stackchan_websocket_v1_MessageType_MESSAGE_TYPE_END:
    message.which_body = stackchan_websocket_v1_WebSocketMessage_audio_pcm_end_tag;
    break;
  default:
    return false;
  }

  std::vector<uint8_t> packet;
  if (!encodeWebSocketMessage(message, packet))
  {
    return false;
  }

  ws_.sendBIN(packet.data(), packet.size());
  return true;
}

void Listening::ringPush(const int16_t *src, size_t samples)
{
  if (samples == 0)
  {
    return;
  }

  if (samples > ring_capacity_samples_)
  {
    src += (samples - ring_capacity_samples_);
    samples = ring_capacity_samples_;
  }

  size_t overflow = (ring_available_ + samples > ring_capacity_samples_) ? (ring_available_ + samples - ring_capacity_samples_) : 0;
  if (overflow > 0)
  {
    ring_read_ = (ring_read_ + overflow) % ring_capacity_samples_;
    ring_available_ -= overflow;
  }

  size_t first = std::min(samples, ring_capacity_samples_ - ring_write_);
  memcpy(ring_buffer_ + ring_write_, src, first * sizeof(int16_t));
  size_t remain = samples - first;
  if (remain > 0)
  {
    memcpy(ring_buffer_, src + first, remain * sizeof(int16_t));
  }
  ring_write_ = (ring_write_ + samples) % ring_capacity_samples_;
  ring_available_ += samples;
}

size_t Listening::ringPop(int16_t *dst, size_t samples)
{
  size_t to_read = std::min(samples, ring_available_);
  if (to_read == 0)
  {
    return 0;
  }

  size_t first = std::min(to_read, ring_capacity_samples_ - ring_read_);
  memcpy(dst, ring_buffer_ + ring_read_, first * sizeof(int16_t));
  size_t remain = to_read - first;
  if (remain > 0)
  {
    memcpy(dst + first, ring_buffer_, remain * sizeof(int16_t));
  }
  ring_read_ = (ring_read_ + to_read) % ring_capacity_samples_;
  ring_available_ -= to_read;
  return to_read;
}
