#pragma once

#include <cstddef>
#include <cstdint>
#include <WebSocketsClient.h>
#include <M5Unified.h>
#include "protocols.hpp"
#include "state_machine.hpp"

class Mic
{
public:
  Mic(WebSocketsClient &ws, StateMachine &sm, int sampleRate);

  // allocate buffers / reset counters; call once from setup
  void init();

  // begin a new streaming session (sends START); returns false if WS not connected
  bool startStreaming();

  // stop streaming (flush remaining DATA and send END)
  bool stopStreaming();

  // perform recording and periodic DATA sends; returns false on send failure
  bool loop();

private:
  bool sendPacket(MessageType type, const int16_t *samples, size_t sampleCount);
  void ringPush(const int16_t *src, size_t samples);
  size_t ringPop(int16_t *dst, size_t samples);

  WebSocketsClient &ws_;
  StateMachine &state_;

  const int sample_rate_;
  const size_t chunk_samples_;
  const size_t mic_read_samples_ = 256;
  const size_t ring_capacity_samples_;

  int16_t *ring_buffer_ = nullptr;
  size_t ring_write_ = 0;
  size_t ring_read_ = 0;
  size_t ring_available_ = 0;

  uint16_t seq_counter_ = 0;
  bool streaming_ = false;
};
