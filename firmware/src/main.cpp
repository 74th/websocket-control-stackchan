// Arduino IDE: board = ESP32S3系, ライブラリ: M5Unified, Links2004/WebSocketsClient
// 事前に: Tools→PSRAM有効（SEはPSRAM無しでも動くよう小さめバッファ）

#include <M5Unified.h>
#include <ESP_SR_M5Unified.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <algorithm>
#include <cstring>
#include <vector>
#include "config.h"
#include "../include/protocols.hpp"
#include "../include/state_machine.hpp"
#include "../include/speaker.hpp"
#include "../include/mic.hpp"

//////////////////// 設定 ////////////////////
const char *WIFI_SSID = WIFI_SSID_H;
const char *WIFI_PASS = WIFI_PASSWORD_H;
const char *SERVER_HOST = SERVER_HOST_H;
const int SERVER_PORT = SERVER_PORT_H;
const char *SERVER_PATH = SERVER_PATH_H; // WebSocket エンドポイント
const int SAMPLE_RATE = 16000;           // 16kHz モノラル
/////////////////////////////////////////////

StateMachine stateMachine;

static WebSocketsClient wsClient;
static Speaker speaker(stateMachine);
static Mic mic(wsClient, stateMachine, SAMPLE_RATE);

// Protocol types are defined in include/protocols.hpp

void connectWiFi()
{
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED)
  {
    delay(300);
  }
}

void handleWsEvent(WStype_t type, uint8_t *payload, size_t length)
{
  switch (type)
  {
  case WStype_DISCONNECTED:
    M5.Display.println("WS: disconnected");
    log_i("WS disconnected");
    break;
  case WStype_CONNECTED:
    M5.Display.printf("WS: connected %s\n", SERVER_PATH);
    log_i("WS connected to %s", SERVER_PATH);
    break;
  case WStype_TEXT:
    //  M5.Display.printf("WS msg: %.*s\n", (int)length, payload);
    break;
  case WStype_BIN:
  {
    if (length < sizeof(WsHeader))
    {
      M5.Display.println("WS bin too short");
      log_i("WS bin too short: %d", (int)length);
      break;
    }

    WsHeader rx{};
    memcpy(&rx, payload, sizeof(WsHeader));
    size_t rx_payload_len = length - sizeof(WsHeader);
    if (rx_payload_len != rx.payloadBytes)
    {
      M5.Display.println("WS payload len mismatch");
      log_i("WS payload len mismatch: expected=%u got=%u", (unsigned)rx.payloadBytes, (unsigned)rx_payload_len);
      break;
    }

    const uint8_t *body = payload + sizeof(WsHeader);
    log_i("WS bin kind=%u len=%d", (unsigned)rx.kind, (int)length);

    switch (static_cast<MessageKind>(rx.kind))
    {
    case MessageKind::AudioWav:
      speaker.handleWavMessage(rx, body, rx_payload_len);
      break;
    default:
      M5.Display.printf("WS bin kind=%u len=%d\n", (unsigned)rx.kind, (int)length);
      break;
    }

    break;
  }
  default:
    break;
  }
}

void onSrEvent(sr_event_t event, int command_id, int phrase_id)
{
  switch(event)
  {
    case SR_EVENT_WAKEWORD:
    log_i("WakeWord Detected!");
    speaker.reset();

    if (mic.startStreaming())
    {
      log_i("Started Mic streaming");
      M5.Display.fillScreen(TFT_GREEN);
      M5.Display.setCursor(10, 10);
      M5.Display.setTextSize(3);
      M5.Display.setTextColor(TFT_BLACK, TFT_GREEN);
      M5.Display.println("Streaming...");
      stateMachine.setState(StateMachine::Streaming);

      ESP_SR_M5.pause();
    }
    else
    {
      log_i("Failed to start Mic streaming");
      M5.Display.fillScreen(TFT_YELLOW);
      M5.Display.setCursor(10, 10);
      M5.Display.setTextSize(3);
      M5.Display.setTextColor(TFT_BLACK, TFT_YELLOW);
    }
    break;
  default:
    log_i("Unknown Event: %d", event);
  }
}

void setup()
{
  auto cfg = M5.config();
  M5.begin(cfg);
  auto mic_cfg = M5.Mic.config();
  mic_cfg.sample_rate = SAMPLE_RATE;
  mic_cfg.stereo = false;
  M5.Mic.config(mic_cfg);
  M5.Mic.begin();

  mic.init();

  // M5.Display.setTextSize(2);
  M5.Display.println("CoreS3 SE - AI Home Agent (WS)");

  connectWiFi();
  M5.Display.printf("WiFi: %s\n", WiFi.localIP().toString().c_str());

  // Mic/Speaker setup
  M5.Speaker.setVolume(200); // 0-255
  speaker.init();

  ESP_SR_M5.onEvent(onSrEvent);
  bool success = ESP_SR_M5.begin();
  log_i("ESP_SR_M5.begin() = %d\n", success);

  wsClient.begin(SERVER_HOST, SERVER_PORT, SERVER_PATH);
  wsClient.onEvent(handleWsEvent);
  wsClient.setReconnectInterval(2000);
  wsClient.enableHeartbeat(15000, 3000, 2);
}

#define AUDIO_SAMPLE_SIZE 256

void loop()
{
  M5.update();
  wsClient.loop();

  if (stateMachine.isIdle())
  {
    static uint32_t loop_count = 0;
    static uint32_t error_count = 0;
    static uint32_t last_log_time = 0;
    static int16_t audio_buf[AUDIO_SAMPLE_SIZE];

    bool success = M5.Mic.record(audio_buf, AUDIO_SAMPLE_SIZE, SAMPLE_RATE);
    if(success)
    {
      ESP_SR_M5.feedAudio(audio_buf, AUDIO_SAMPLE_SIZE);

      uint32_t now = millis();
      if (now - last_log_time >= 1000)
      {
        int32_t sum = 0;
        for (int i = 0; i < 10; i++)
        {
          sum += abs(audio_buf[i]);
        }
        log_i("loop: count=%d, avg_level=%d, errors=%d, interval=%dms", loop_count, sum / 10, error_count, now - last_log_time);
        last_log_time = now;
      }
      loop_count++;
    }
    else
    {
      error_count++;
      if (error_count % 100 == 0)
      {
        log_w("WARNING: M5.Mic.record failed, count=%d\n", error_count);
      }
    }
  }
  else if (stateMachine.isStreaming())
  {
    if (!mic.loop())
    {
      M5.Display.println("WS send failed (data)");
      log_i("WS send failed (data)");
      stateMachine.setState(StateMachine::Idle);
      return;
    }

    // 無音が3秒続いたら終了
    if (mic.shouldStopForSilence())
    {
      log_i("Auto stop: silence detected (avg=%ld)", static_cast<long>(mic.getLastLevel()));
      if (!mic.stopStreaming())
      {
        M5.Display.println("WS send failed (tail/end)");
        log_i("WS send failed (tail/end)");
      }
      stateMachine.setState(StateMachine::Idle);
      M5.Display.println("Stopped (silence)");

      // 終了直後のTTS再生でMic/Speakerが競合しないよう、少し待つ
      delay(20);
    }
  }

  // ---- Downlink TTS playback (handled by Speaker) ----
  speaker.loop();
}
