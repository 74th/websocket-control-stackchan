#pragma once

#include <cstddef>
#include <cstdint>
#include <WebSocketsClient.h>
#include <M5Unified.h>
#include "protocols.hpp"
#include "state_machine.hpp"

class Listening
{
public:
  Listening(WebSocketsClient &ws, StateMachine &sm, int sampleRate);

  // allocate buffers / reset counters; call once from setup
  void init();

  // begin a new streaming session (sends START); returns false if WS not connected
  bool startStreaming();

  // stop streaming (flush remaining DATA and send END)
  bool stopStreaming();

  // perform recording and periodic DATA sends; handles errors/silence internally
  void loop();

  // 最近の平均音量（絶対値平均）を取得
  int32_t getLastLevel() const { return last_level_; }

  // 無音が所定時間続いているか判定
  bool shouldStopForSilence() const;

private:
  void updateLevelStats(const int16_t *samples, size_t sampleCount);
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
  bool events_registered_ = false;

  // 無音判定関連
  int32_t last_level_ = 0;
  uint32_t silence_since_ms_ = 0;
  static constexpr int32_t kSilenceLevelThreshold = 200;     // 平均絶対値がこの値以下を無音とみなす
  static constexpr uint32_t kSilenceDurationMs = 3000;        // 無音とみなす継続時間
};
