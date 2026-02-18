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
}

void WakeUpWord::begin()
{
  M5.Mic.begin();
  ESP_SR_M5.setMode(SR_MODE_WAKEWORD);
  ESP_SR_M5.resume();
}

void WakeUpWord::end()
{
  M5.Mic.end();
  ESP_SR_M5.pause();
}

void WakeUpWord::feedAudio(const int16_t *samples, size_t count)
{
  ESP_SR_M5.feedAudio(samples, count);
}

void WakeUpWord::loop()
{
  if (!state_.isIdle())
  {
    return;
  }

  constexpr size_t kAudioSampleSize = 256;
  static int16_t audio_buf[kAudioSampleSize];

  bool success = M5.Mic.record(audio_buf, kAudioSampleSize, sample_rate_);
  if (success)
  {
    feedAudio(audio_buf, kAudioSampleSize);

    uint32_t now = millis();
    if (now - last_log_time_ >= 1000)
    {
      int32_t sum = 0;
      for (int i = 0; i < 10; i++)
      {
        sum += abs(audio_buf[i]);
      }
      log_i("idle loop: count=%lu, avg_level=%ld, errors=%lu, interval=%lu ms",
            static_cast<unsigned long>(loop_count_),
            static_cast<long>(sum / 10),
            static_cast<unsigned long>(error_count_),
            static_cast<unsigned long>(now - last_log_time_));
      last_log_time_ = now;
    }
    loop_count_++;
  }
  else
  {
    error_count_++;
    if (error_count_ % 100 == 0)
    {
      log_w("WARNING: M5.Mic.record failed, count=%lu", static_cast<unsigned long>(error_count_));
    }
  }
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
