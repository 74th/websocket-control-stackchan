#include "listening.hpp"
#include <algorithm>
#include <cstring>
#include <vector>
#include <cstdlib>

Listening::Listening(WebSocketsClient &ws, StateMachine &sm, int sampleRate)
    : ws_(ws), state_(sm), sample_rate_(sampleRate),
      chunk_samples_(static_cast<size_t>(sampleRate) / 2),
      ring_capacity_samples_(static_cast<size_t>(sampleRate) * 2)
{
}

void Listening::init()
{
  if (!events_registered_)
  {
    events_registered_ = true;
    state_.addStateEntryEvent(StateMachine::Listening, [this](StateMachine::State, StateMachine::State) {
      M5.Mic.begin();
      startStreaming();
    });
    state_.addStateExitEvent(StateMachine::Listening, [this](StateMachine::State next, StateMachine::State) {
      stopStreaming();
      M5.Mic.end();
    });

    // Speaking 中はマイクを停止（安全のためエントリでも end）
    state_.addStateEntryEvent(StateMachine::Speaking, [](StateMachine::State, StateMachine::State) {
      M5.Mic.end();
    });
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

bool Listening::startStreaming()
{
  ring_write_ = ring_read_ = ring_available_ = 0;
  seq_counter_ = 0;
  last_level_ = 0;
  silence_since_ms_ = 0;
  streaming_ = true;
  return sendPacket(MessageType::START, nullptr, 0);
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
      if (!sendPacket(MessageType::DATA, tail_buf.data(), sent))
      {
        ok = false;
        break;
      }
      to_send -= sent;
    }
  }

  streaming_ = false;
  ok = sendPacket(MessageType::END, nullptr, 0) && ok;
  return ok;
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
    if (!sendPacket(MessageType::DATA, send_buf.data(), got))
    {
      streaming_ = false;
      M5.Display.println("WS send failed (data)");
      log_i("WS send failed (data)");
      state_.setState(StateMachine::Idle);
      return;
    }
  }

  // 無音が3秒続いたら終了
  if (shouldStopForSilence())
  {
    log_i("Auto stop: silence detected (avg=%ld)", static_cast<long>(last_level_));
    M5.Display.fillScreen(TFT_BLACK);
    M5.Display.setCursor(10, 10);
    M5.Display.setTextSize(3);
    M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
    if (!stopStreaming())
    {
      M5.Display.println("WS send failed (tail/end)");
      log_i("WS send failed (tail/end)");
    }
    state_.setState(StateMachine::Idle);
    M5.Display.println("Stopped (silence)");

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

bool Listening::sendPacket(MessageType type, const int16_t *samples, size_t sampleCount)
{
  if ((WiFi.status() != WL_CONNECTED) || !ws_.isConnected())
  {
    return false;
  }

  WsHeader header{};
  header.kind = static_cast<uint8_t>(MessageKind::AudioPcm);
  header.messageType = static_cast<uint8_t>(type);
  header.reserved = 0;
  header.seq = seq_counter_++;
  header.payloadBytes = static_cast<uint16_t>(sampleCount * sizeof(int16_t));

  std::vector<uint8_t> packet;
  packet.resize(sizeof(WsHeader) + header.payloadBytes);
  memcpy(packet.data(), &header, sizeof(WsHeader));
  if (header.payloadBytes > 0 && samples != nullptr)
  {
    memcpy(packet.data() + sizeof(WsHeader), samples, header.payloadBytes);
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
