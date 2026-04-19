#include <M5Unified.h>
#include <ESP_SR_M5Unified.h>
#include <utility>
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
  ESP_SR_M5.pause();
  delay(10);
  M5.Mic.end();
  delay(20);
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
  }
}

void WakeUpWord::setWakeWordDetectedCallback(std::function<void()> cb)
{
  on_wake_word_detected_ = std::move(cb);
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
    if (on_wake_word_detected_)
    {
      on_wake_word_detected_();
    }
    break;
  default:
    log_i("Unknown Event: %d", event);
    break;
  }
}
