/*
 * ESP32 HAL for Speech Recognition with M5Unified - Implementation
 * Based on esp32-hal-sr.c but adapted for M5Unified microphone
 */
#include "sdkconfig.h"
#if (CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32P4) && (CONFIG_MODEL_IN_FLASH || CONFIG_MODEL_IN_SDCARD)

#if !defined(ARDUINO_PARTITION_esp_sr_32) && !defined(ARDUINO_PARTITION_esp_sr_16) && !defined(ARDUINO_PARTITION_esp_sr_8)
#warning Compatible partition must be selected for ESP_SR to work
#endif

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <sys/queue.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "esp_task_wdt.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_mn_speech_commands.h"
#include "esp_process_sdkconfig.h"
#include "esp_afe_sr_models.h"
#include "esp_mn_models.h"
#include "esp_wn_iface.h"
#include "esp_wn_models.h"
#include "esp_afe_sr_iface.h"
#include "esp_mn_iface.h"
#include "model_path.h"

#include "driver/i2s_common.h"
#include "esp32-hal-sr-m5.h"
#include "esp32-hal-log.h"

#undef ESP_GOTO_ON_FALSE
#define ESP_GOTO_ON_FALSE(a, err_code, goto_tag, format, ...) \
  do                                                          \
  {                                                           \
    if (unlikely(!(a)))                                       \
    {                                                         \
      log_e(format, ##__VA_ARGS__);                           \
      ret = err_code;                                         \
      goto goto_tag;                                          \
    }                                                         \
  } while (0)

#undef ESP_RETURN_ON_FALSE
#define ESP_RETURN_ON_FALSE(a, err_code, format, ...) \
  do                                                  \
  {                                                   \
    if (unlikely(!(a)))                               \
    {                                                 \
      log_e(format, ##__VA_ARGS__);                   \
      return err_code;                                \
    }                                                 \
  } while (0)

#define NEED_DELETE BIT0
#define FEED_DELETED BIT1
#define DETECT_DELETED BIT2
#define PAUSE_FEED BIT3
#define PAUSE_DETECT BIT4
#define RESUME_FEED BIT5
#define RESUME_DETECT BIT6

typedef struct
{
  wakenet_state_t wakenet_mode;
  esp_mn_state_t state;
  int command_id;
  int phrase_id;
} sr_result_t;

typedef struct
{
  model_iface_data_t *model_data;
  const esp_mn_iface_t *multinet;
  const esp_afe_sr_iface_t *afe_handle;
  esp_afe_sr_data_t *afe_data;
  int16_t *afe_in_buffer;
  sr_mode_t mode;
  uint8_t rx_chan_num;
  sr_event_cb_m5 user_cb;
  void *user_cb_arg;
  sr_fill_cb_m5 fill_cb;
  void *fill_cb_arg;
  TaskHandle_t feed_task;
  TaskHandle_t detect_task;
  TaskHandle_t handle_task;
  QueueHandle_t result_que;
  EventGroupHandle_t event_group;
} sr_data_m5_t;

// AFE always expects 3-channel format: [ch0, ch1, ch2]
// For mono input: [Mic, 0, 0] (MN format)
static int SR_CHANNEL_NUM = 2;

static srmodel_list_t *models_m5 = NULL;
static sr_data_m5_t *g_sr_data_m5 = NULL;

esp_err_t sr_set_mode_m5(sr_mode_t mode);

void sr_handler_task_m5(void *pvParam)
{
  while (true)
  {
    sr_result_t result;
    if (xQueueReceive(g_sr_data_m5->result_que, &result, portMAX_DELAY) != pdTRUE)
    {
      continue;
    }

    if (WAKENET_DETECTED == result.wakenet_mode)
    {
      if (g_sr_data_m5->user_cb)
      {
        g_sr_data_m5->user_cb(g_sr_data_m5->user_cb_arg, SR_EVENT_WAKEWORD, -1, -1);
      }
      continue;
    }

    if (WAKENET_CHANNEL_VERIFIED == result.wakenet_mode)
    {
      if (g_sr_data_m5->user_cb)
      {
        g_sr_data_m5->user_cb(g_sr_data_m5->user_cb_arg, SR_EVENT_WAKEWORD_CHANNEL, result.command_id, -1);
      }
      continue;
    }

    if (ESP_MN_STATE_DETECTED == result.state)
    {
      if (g_sr_data_m5->user_cb)
      {
        g_sr_data_m5->user_cb(g_sr_data_m5->user_cb_arg, SR_EVENT_COMMAND, result.command_id, result.phrase_id);
      }
      continue;
    }

    if (ESP_MN_STATE_TIMEOUT == result.state)
    {
      if (g_sr_data_m5->user_cb)
      {
        g_sr_data_m5->user_cb(g_sr_data_m5->user_cb_arg, SR_EVENT_TIMEOUT, -1, -1);
      }
      continue;
    }
  }
  vTaskDelete(NULL);
}

static void audio_feed_task_m5(void *arg)
{
  size_t bytes_read = 0;
  int audio_chunksize = g_sr_data_m5->afe_handle->get_feed_chunksize(g_sr_data_m5->afe_data);
  log_i("audio_chunksize=%d, feed_channel=%d", audio_chunksize, SR_CHANNEL_NUM);

  /* Allocate audio buffer and check for result */
  int16_t *audio_buffer = heap_caps_malloc(audio_chunksize * sizeof(int16_t) * g_sr_data_m5->rx_chan_num, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  if (NULL == audio_buffer)
  {
    esp_system_abort("No mem for audio buffer");
  }
  g_sr_data_m5->afe_in_buffer = audio_buffer;

  while (true)
  {
    EventBits_t bits = xEventGroupGetBits(g_sr_data_m5->event_group);
    if (NEED_DELETE & bits)
    {
      xEventGroupSetBits(g_sr_data_m5->event_group, FEED_DELETED);
      break;
    }
    if (PAUSE_FEED & bits)
    {
      xEventGroupWaitBits(g_sr_data_m5->event_group, PAUSE_FEED | RESUME_FEED, 1, 1, portMAX_DELAY);
    }

    /* Read audio data from M5 callback */
    if (g_sr_data_m5->fill_cb == NULL)
    {
      vTaskDelay(100);
      continue;
    }

    esp_err_t err = g_sr_data_m5->fill_cb(
        g_sr_data_m5->fill_cb_arg,
        (char *)audio_buffer,
        audio_chunksize * g_sr_data_m5->rx_chan_num * sizeof(int16_t),
        &bytes_read,
        portMAX_DELAY);

    if (err != ESP_OK)
    {
      log_e("audio_feed_task_m5: fill_cb failed, err=%d", err);
      vTaskDelay(100);
      continue;
    }

    /* Feed samples of an audio stream to the AFE_SR */
    g_sr_data_m5->afe_handle->feed(g_sr_data_m5->afe_data, audio_buffer);
    vTaskDelay(2);
  }
  vTaskDelete(NULL);
}

static void audio_detect_task_m5(void *arg)
{
  int afe_chunksize = g_sr_data_m5->afe_handle->get_fetch_chunksize(g_sr_data_m5->afe_data);

  // Only check mu_chunksize if multinet is initialized
  if (g_sr_data_m5->multinet != NULL && g_sr_data_m5->model_data != NULL)
  {
    int mu_chunksize = g_sr_data_m5->multinet->get_samp_chunksize(g_sr_data_m5->model_data);
    assert(mu_chunksize == afe_chunksize);
  }

  log_i("------------detect start------------");

  while (true)
  {
    EventBits_t bits = xEventGroupGetBits(g_sr_data_m5->event_group);
    if (NEED_DELETE & bits)
    {
      xEventGroupSetBits(g_sr_data_m5->event_group, DETECT_DELETED);
      break;
    }
    if (PAUSE_DETECT & bits)
    {
      xEventGroupWaitBits(g_sr_data_m5->event_group, PAUSE_DETECT | RESUME_DETECT, 1, 1, portMAX_DELAY);
    }

    afe_fetch_result_t *res = g_sr_data_m5->afe_handle->fetch(g_sr_data_m5->afe_data);

    static uint32_t fetch_fail_count = 0;

    if (!res || res->ret_value == ESP_FAIL)
    {
      fetch_fail_count++;
      if (fetch_fail_count % 100 == 1)
      {
        log_w("audio_detect_task_m5: fetch failed, count=%d", fetch_fail_count);
      }
      continue;
    }

    if (g_sr_data_m5->mode == SR_MODE_WAKEWORD)
    {
      if (res->wakeup_state == WAKENET_DETECTED)
      {
        log_d("wakeword detected");
        sr_result_t result = {
            .wakenet_mode = WAKENET_DETECTED,
            .state = ESP_MN_STATE_DETECTING,
            .command_id = 0,
            .phrase_id = 0,
        };
        xQueueSend(g_sr_data_m5->result_que, &result, 0);
      }
      else if (res->wakeup_state == WAKENET_CHANNEL_VERIFIED)
      {
        sr_set_mode_m5(SR_MODE_OFF);
        log_d("AFE_FETCH_CHANNEL_VERIFIED, channel index: %d", res->trigger_channel_id);
        sr_result_t result = {
            .wakenet_mode = WAKENET_CHANNEL_VERIFIED,
            .state = ESP_MN_STATE_DETECTING,
            .command_id = res->trigger_channel_id,
            .phrase_id = 0,
        };
        xQueueSend(g_sr_data_m5->result_que, &result, 0);
      }
    }

    if (g_sr_data_m5->mode == SR_MODE_COMMAND)
    {
      // Skip command detection if multinet is not initialized
      if (g_sr_data_m5->multinet == NULL || g_sr_data_m5->model_data == NULL)
      {
        continue;
      }

      esp_mn_state_t mn_state = ESP_MN_STATE_DETECTING;
      mn_state = g_sr_data_m5->multinet->detect(g_sr_data_m5->model_data, res->data);

      if (ESP_MN_STATE_DETECTING == mn_state)
      {
        continue;
      }

      if (ESP_MN_STATE_TIMEOUT == mn_state)
      {
        sr_set_mode_m5(SR_MODE_OFF);
        log_d("Time out");
        sr_result_t result = {
            .wakenet_mode = WAKENET_NO_DETECT,
            .state = mn_state,
            .command_id = 0,
            .phrase_id = 0,
        };
        xQueueSend(g_sr_data_m5->result_que, &result, 0);
        continue;
      }

      if (ESP_MN_STATE_DETECTED == mn_state)
      {
        sr_set_mode_m5(SR_MODE_OFF);
        esp_mn_results_t *mn_result = g_sr_data_m5->multinet->get_results(g_sr_data_m5->model_data);
        for (int i = 0; i < mn_result->num; i++)
        {
          log_d("TOP %d, command_id: %d, phrase_id: %d, prob: %f", i + 1, mn_result->command_id[i], mn_result->phrase_id[i], mn_result->prob[i]);
        }

        int sr_command_id = mn_result->command_id[0];
        int sr_phrase_id = mn_result->phrase_id[0];
        log_d("Detected command : %d, phrase: %d", sr_command_id, sr_phrase_id);
        sr_result_t result = {
            .wakenet_mode = WAKENET_NO_DETECT,
            .state = mn_state,
            .command_id = sr_command_id,
            .phrase_id = sr_phrase_id,
        };
        xQueueSend(g_sr_data_m5->result_que, &result, 0);
        continue;
      }
      log_e("Exception unhandled");
    }
  }
  vTaskDelete(NULL);
}

esp_err_t sr_set_mode_m5(sr_mode_t mode)
{
  ESP_RETURN_ON_FALSE(NULL != g_sr_data_m5, ESP_ERR_INVALID_STATE, "SR is not running");
  switch (mode)
  {
  case SR_MODE_OFF:
    if (g_sr_data_m5->mode == SR_MODE_WAKEWORD)
    {
      g_sr_data_m5->afe_handle->disable_wakenet(g_sr_data_m5->afe_data);
    }
    break;
  case SR_MODE_WAKEWORD:
    if (g_sr_data_m5->mode != SR_MODE_WAKEWORD)
    {
      g_sr_data_m5->afe_handle->enable_wakenet(g_sr_data_m5->afe_data);
    }
    break;
  case SR_MODE_COMMAND:
    if (g_sr_data_m5->mode == SR_MODE_WAKEWORD)
    {
      g_sr_data_m5->afe_handle->disable_wakenet(g_sr_data_m5->afe_data);
    }
    break;
  default:
    return ESP_FAIL;
  }
  g_sr_data_m5->mode = mode;
  return ESP_OK;
}

esp_err_t sr_start_m5(
    sr_fill_cb_m5 fill_cb,
    void *fill_cb_arg,
    sr_channels_t rx_chan,
    sr_mode_t mode,
    const char *input_format,
    const sr_cmd_t sr_commands[],
    size_t cmd_number,
    sr_event_cb_m5 cb,
    void *cb_arg)
{
  esp_err_t ret = ESP_OK;
  ESP_RETURN_ON_FALSE(NULL == g_sr_data_m5, ESP_ERR_INVALID_STATE, "SR already running");

  g_sr_data_m5 = heap_caps_calloc(1, sizeof(sr_data_m5_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  ESP_RETURN_ON_FALSE(NULL != g_sr_data_m5, ESP_ERR_NO_MEM, "Failed create sr data");

  g_sr_data_m5->result_que = xQueueCreate(3, sizeof(sr_result_t));
  ESP_GOTO_ON_FALSE(NULL != g_sr_data_m5->result_que, ESP_ERR_NO_MEM, err, "Failed create result queue");

  g_sr_data_m5->event_group = xEventGroupCreate();
  ESP_GOTO_ON_FALSE(NULL != g_sr_data_m5->event_group, ESP_ERR_NO_MEM, err, "Failed create event_group");

  BaseType_t ret_val;
  g_sr_data_m5->user_cb = cb;
  g_sr_data_m5->user_cb_arg = cb_arg;
  g_sr_data_m5->fill_cb = fill_cb;
  g_sr_data_m5->fill_cb_arg = fill_cb_arg;
  g_sr_data_m5->rx_chan_num = rx_chan + 1;
  g_sr_data_m5->mode = mode;

  // Init Model
  log_d("init model");
  models_m5 = esp_srmodel_init("model");

  // Load WakeWord Detection
  afe_config_t *afe_config = afe_config_init(input_format, models_m5, AFE_TYPE_SR, AFE_MODE_LOW_COST);
  g_sr_data_m5->afe_handle = esp_afe_handle_from_config(afe_config);
  log_d("load wakenet '%s'", afe_config->wakenet_model_name);
  g_sr_data_m5->afe_data = g_sr_data_m5->afe_handle->create_from_config(afe_config);
  afe_config_free(afe_config);

  // Load Custom Command Detection only if commands are provided
  if (cmd_number > 0)
  {
    char *mn_name = esp_srmodel_filter(models_m5, ESP_MN_PREFIX, ESP_MN_ENGLISH);
    log_d("load multinet '%s'", mn_name);
    g_sr_data_m5->multinet = esp_mn_handle_from_name(mn_name);
    log_d("load model_data '%s'", mn_name);
    g_sr_data_m5->model_data = g_sr_data_m5->multinet->create(mn_name, 5760);

    // Add commands
    esp_mn_commands_alloc((esp_mn_iface_t *)g_sr_data_m5->multinet, (model_iface_data_t *)g_sr_data_m5->model_data);
    log_i("add %d commands", cmd_number);
    for (size_t i = 0; i < cmd_number; i++)
    {
      esp_mn_commands_add(sr_commands[i].command_id, (char *)(sr_commands[i].phoneme));
      log_i("  cmd[%d] phrase[%d]:'%s'", sr_commands[i].command_id, i, sr_commands[i].str);
    }

    // Load commands
    esp_mn_error_t *err_id = esp_mn_commands_update();
    if (err_id)
    {
      for (int i = 0; i < err_id->num; i++)
      {
        log_e("err cmd id:%d", err_id->phrases[i]->command_id);
      }
    }
  }
  else
  {
    log_i("No commands provided, skipping multinet initialization (wakeword-only mode)");
    g_sr_data_m5->multinet = NULL;
    g_sr_data_m5->model_data = NULL;
  }

  // Start tasks
  log_d("start tasks");
  ret_val = xTaskCreatePinnedToCore(&audio_feed_task_m5, "SR Feed Task M5", 4 * 1024, NULL, 5, &g_sr_data_m5->feed_task, 0);
  ESP_GOTO_ON_FALSE(pdPASS == ret_val, ESP_FAIL, err, "Failed create audio feed task");
  vTaskDelay(10);
  ret_val = xTaskCreatePinnedToCore(&audio_detect_task_m5, "SR Detect Task M5", 8 * 1024, NULL, 5, &g_sr_data_m5->detect_task, 1);
  ESP_GOTO_ON_FALSE(pdPASS == ret_val, ESP_FAIL, err, "Failed create audio detect task");
  ret_val = xTaskCreatePinnedToCore(&sr_handler_task_m5, "SR Handler Task M5", 6 * 1024, NULL, configMAX_PRIORITIES - 1, &g_sr_data_m5->handle_task, 1);
  ESP_GOTO_ON_FALSE(pdPASS == ret_val, ESP_FAIL, err, "Failed create audio handler task");

  return ESP_OK;
err:
  sr_stop_m5();
  return ret;
}

esp_err_t sr_stop_m5(void)
{
  ESP_RETURN_ON_FALSE(NULL != g_sr_data_m5, ESP_ERR_INVALID_STATE, "SR is not running");

  /**
   * Waiting for all task stopped
   * TODO: A task creation failure cannot be handled correctly now
   * */
  vTaskDelete(g_sr_data_m5->handle_task);
  xEventGroupSetBits(g_sr_data_m5->event_group, NEED_DELETE);
  xEventGroupWaitBits(g_sr_data_m5->event_group, NEED_DELETE | FEED_DELETED | DETECT_DELETED, 1, 1, portMAX_DELAY);

  if (g_sr_data_m5->result_que)
  {
    vQueueDelete(g_sr_data_m5->result_que);
    g_sr_data_m5->result_que = NULL;
  }

  if (g_sr_data_m5->event_group)
  {
    vEventGroupDelete(g_sr_data_m5->event_group);
    g_sr_data_m5->event_group = NULL;
  }

  if (g_sr_data_m5->model_data && g_sr_data_m5->multinet)
  {
    g_sr_data_m5->multinet->destroy(g_sr_data_m5->model_data);
  }

  if (g_sr_data_m5->afe_data)
  {
    g_sr_data_m5->afe_handle->destroy(g_sr_data_m5->afe_data);
  }

  if (g_sr_data_m5->afe_in_buffer)
  {
    heap_caps_free(g_sr_data_m5->afe_in_buffer);
  }

  heap_caps_free(g_sr_data_m5);
  g_sr_data_m5 = NULL;
  return ESP_OK;
}

esp_err_t sr_pause_m5(void)
{
  ESP_RETURN_ON_FALSE(NULL != g_sr_data_m5, ESP_ERR_INVALID_STATE, "SR is not running");
  xEventGroupSetBits(g_sr_data_m5->event_group, PAUSE_FEED | PAUSE_DETECT);
  return ESP_OK;
}

esp_err_t sr_resume_m5(void)
{
  ESP_RETURN_ON_FALSE(NULL != g_sr_data_m5, ESP_ERR_INVALID_STATE, "SR is not running");
  xEventGroupSetBits(g_sr_data_m5->event_group, RESUME_FEED | RESUME_DETECT);
  return ESP_OK;
}

#endif // CONFIG_IDF_TARGET_ESP32S3
