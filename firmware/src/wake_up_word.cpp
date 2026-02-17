#include <M5Unified.h>
#include <ESP_SR_M5Unified.h>
#include "wake_up_word.hpp"

namespace
{
WakeUpWord *g_wuw = nullptr;
}

void WakeUpWord::init()
{
  g_wuw = this;

  ESP_SR_M5.onEvent(onSrEventForward);
  bool success = ESP_SR_M5.begin();
  log_i("ESP_SR_M5.begin() = %d", success);

  // Idle→Listening への遷移時にマイクを止めて SR を一時停止
  state_.addStateExitEvent(StateMachine::Idle, [](StateMachine::State, StateMachine::State) {
    M5.Mic.end();
    ESP_SR_M5.pause();
  });

  // Listening→Idle に戻ったら WakeWord モードで再開
  state_.addStateEntryEvent(StateMachine::Idle, [](StateMachine::State, StateMachine::State) {
    M5.Mic.begin();
    ESP_SR_M5.setMode(SR_MODE_WAKEWORD);
    ESP_SR_M5.resume();
  });
}

void WakeUpWord::feedAudio(const int16_t *samples, size_t count)
{
  ESP_SR_M5.feedAudio(samples, count);
}

void WakeUpWord::onSrEventForward(sr_event_t event, int command_id, int phrase_id)
{
  if (g_wuw)
  {
    g_wuw->handleSrEvent(event, command_id, phrase_id);
  }
}

void WakeUpWord::handleSrEvent(sr_event_t event, int command_id, int phrase_id)
{
  switch (event)
  {
  case SR_EVENT_WAKEWORD:
    log_i("WakeWord Detected!");
    log_i("WakeWord Detected: entering Listening state");
    state_.setState(StateMachine::Listening);
    break;
  default:
    log_i("Unknown Event: %d", event);
    break;
  }
}
