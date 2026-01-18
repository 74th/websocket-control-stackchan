#pragma once

#include <vector>
#include <cstdint>
#include <M5Unified.h>
#include "protocols.hpp"
#include "state_machine.hpp"

class Speaker
{
public:
  explicit Speaker(StateMachine &sm) : state_(sm) {}

  // Initialize internal buffers/state (call once from setup)
  void init();

  // Process one WS audio message of kind AudioWav
  void handleWavMessage(const WsHeader &hdr, const uint8_t *body, size_t bodyLen);

  // Called from main loop to progress playback state
  void loop();

  // Reset any buffered audio / playback state
  void reset();

private:
  StateMachine &state_;
  std::vector<uint8_t> buffer_[3];
  uint8_t current_buffer_ = 0;
  bool playing_ = false;
  bool mic_was_enabled_ = false;
  bool streaming_ = false;
  uint16_t next_seq_ = 0;
  uint32_t sample_rate_ = 24000;
  uint16_t channels_ = 1;
};
