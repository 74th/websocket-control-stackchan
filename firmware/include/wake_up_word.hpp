#pragma once

#include <cstddef>
#include <cstdint>
#include <ESP_SR_M5Unified.h>
#include "state_machine.hpp"

class WakeUpWord
{
public:
  WakeUpWord(StateMachine &state, int sampleRate) : state_(state), sample_rate_(sampleRate) {}

  // ESP_SR を初期化し、ステートマシンのエントリ/エグジットイベントや SR のイベントハンドラを登録する
  void init();

  // ステート開始/終了時の処理（Idle 入退場で利用）
  void begin();
  void end();

  // SR にオーディオを供給する（Idle ループで利用）
  void feedAudio(const int16_t *samples, size_t count);

  // Idle ステート中の処理（マイク入力→SRへ供給）
  void loop();

private:
  static void onSrEventForward(sr_event_t event, int command_id, int phrase_id);
  void handleSrEvent(sr_event_t event, int command_id, int phrase_id);

  StateMachine &state_;
  const int sample_rate_;

  // Idle 時のログ用カウンタ
  uint32_t loop_count_ = 0;
  uint32_t error_count_ = 0;
  uint32_t last_log_time_ = 0;
};
