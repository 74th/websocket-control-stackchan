/*
 * ESP_SR_M5Unified - ESP-SR wrapper for M5Unified
 *
 * This library wraps ESP-SR to work with M5Unified's microphone system.
 * Instead of using I2S directly, it accepts audio data from M5.Mic.record().
 */

#pragma once
#include "sdkconfig.h"
#if (CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32P4) && (CONFIG_MODEL_IN_FLASH || CONFIG_MODEL_IN_SDCARD)

#include "esp32-hal-sr-m5.h"

typedef void (*sr_cb_m5)(sr_event_t event, int command_id, int phrase_id);

class ESP_SR_M5Unified_Class
{
private:
  sr_cb_m5 cb;
  int16_t *audio_buffer;
  size_t buffer_size;
  bool buffer_ready;

public:
  ESP_SR_M5Unified_Class();
  ~ESP_SR_M5Unified_Class();

  void onEvent(sr_cb_m5 cb);

  /**
   * Initialize ESP-SR with M5Unified microphone support
   * @param sr_commands Array of speech recognition commands
   * @param sr_commands_len Number of commands in the array
   * @param mode Initial SR mode (SR_MODE_WAKEWORD or SR_MODE_COMMAND)
   * @param rx_chan Number of microphone channels (SR_CHANNELS_MONO or SR_CHANNELS_STEREO)
   * @return true if initialization succeeded
   */
  bool begin(
      const sr_cmd_t *sr_commands = nullptr,
      size_t sr_commands_len = 0,
      sr_mode_t mode = SR_MODE_WAKEWORD,
      sr_channels_t rx_chan = SR_CHANNELS_MONO);

  bool end(void);
  bool setMode(sr_mode_t mode);
  bool pause(void);
  bool resume(void);

  /**
   * Feed audio data from M5.Mic.record() to ESP-SR
   * Call this in your loop() with the buffer from M5.Mic.record()
   * @param data Audio buffer from M5.Mic.record()
   * @param samples Number of samples in the buffer
   */
  void feedAudio(const int16_t *data, size_t samples);

  void _sr_event(sr_event_t event, int command_id, int phrase_id);
  esp_err_t _fill(void *out, size_t len, size_t *bytes_read, uint32_t timeout_ms);
};

#if !defined(NO_GLOBAL_INSTANCES) && !defined(NO_GLOBAL_ESP_SR_M5)
extern ESP_SR_M5Unified_Class ESP_SR_M5;
#endif

#endif // CONFIG_IDF_TARGET_ESP32S3
