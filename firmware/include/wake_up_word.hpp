#pragma once

#include <cstddef>
#include <cstdint>
#include <ESP_SR_M5Unified.h>
#include "state_machine.hpp"

class Mic;
class Speaker;

class WakeUpWord
{
public:
  WakeUpWord(Mic &mic, Speaker &speaker, StateMachine &state) : mic_(mic), speaker_(speaker), state_(state) {}

  // ESP_SR を初期化し、ステートマシンのエントリ/エグジットイベントや SR のイベントハンドラを登録する
  void init();

  // SR にオーディオを供給する（Idle ループで利用）
  void feedAudio(const int16_t *samples, size_t count);

private:
  static void onSrEventForward(sr_event_t event, int command_id, int phrase_id);
  void handleSrEvent(sr_event_t event, int command_id, int phrase_id);

  Mic &mic_;
  Speaker &speaker_;
  StateMachine &state_;
};
