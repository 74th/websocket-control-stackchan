/*
 * ESP32 HAL for Speech Recognition with M5Unified
 * Based on esp32-hal-sr.h but adapted for M5Unified microphone
 */

#pragma once
#include "sdkconfig.h"
#if (CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32P4) && (CONFIG_MODEL_IN_FLASH || CONFIG_MODEL_IN_SDCARD)

#include "driver/i2s_types.h"
#include "esp_err.h"

#ifdef __cplusplus
extern "C"
{
#endif

#define SR_CMD_STR_LEN_MAX 64
#define SR_CMD_PHONEME_LEN_MAX 64

  typedef struct sr_cmd_t
  {
    int command_id;
    char str[SR_CMD_STR_LEN_MAX];
    char phoneme[SR_CMD_PHONEME_LEN_MAX];
  } sr_cmd_t;

  typedef enum
  {
    SR_EVENT_WAKEWORD,         // WakeWord Detected
    SR_EVENT_WAKEWORD_CHANNEL, // WakeWord Channel Verified
    SR_EVENT_COMMAND,          // Command Detected
    SR_EVENT_TIMEOUT,          // Command Timeout
    SR_EVENT_MAX
  } sr_event_t;

  typedef enum
  {
    SR_MODE_OFF,      // Detection Off
    SR_MODE_WAKEWORD, // WakeWord Detection
    SR_MODE_COMMAND,  // Command Detection
    SR_MODE_MAX
  } sr_mode_t;

  typedef enum
  {
    SR_CHANNELS_MONO,
    SR_CHANNELS_STEREO,
    SR_CHANNELS_MAX
  } sr_channels_t;

  typedef void (*sr_event_cb_m5)(void *arg, sr_event_t event, int command_id, int phrase_id);
  typedef esp_err_t (*sr_fill_cb_m5)(void *arg, void *out, size_t len, size_t *bytes_read, uint32_t timeout_ms);

  esp_err_t sr_start_m5(
      sr_fill_cb_m5 fill_cb,
      void *fill_cb_arg,
      sr_channels_t rx_chan,
      sr_mode_t mode,
      const char *input_format,
      const sr_cmd_t *sr_commands,
      size_t cmd_number,
      sr_event_cb_m5 cb,
      void *cb_arg);

  esp_err_t sr_stop_m5(void);
  esp_err_t sr_pause_m5(void);
  esp_err_t sr_resume_m5(void);
  esp_err_t sr_set_mode_m5(sr_mode_t mode);

#ifdef __cplusplus
}
#endif

#endif // CONFIG_IDF_TARGET_ESP32S3
