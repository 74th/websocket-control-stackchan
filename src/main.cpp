// Arduino IDE: board = ESP32S3系, ライブラリ: M5Unified, Links2004/WebSocketsClient
// 事前に: Tools→PSRAM有効（SEはPSRAM無しでも動くよう小さめバッファ）

#include <M5Unified.h>
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

void setup()
{
  auto cfg = M5.config();
  M5.begin(cfg);
  mic.init();

  M5.Display.setTextSize(2);
  M5.Display.println("CoreS3 SE - AI Home Agent (WS)");

  connectWiFi();
  M5.Display.printf("WiFi: %s\n", WiFi.localIP().toString().c_str());

  // Mic/Speaker setup
  M5.Speaker.setVolume(200); // 0-255
  M5.Mic.begin();
  speaker.init();

  wsClient.begin(SERVER_HOST, SERVER_PORT, SERVER_PATH);
  wsClient.onEvent([](WStype_t type, uint8_t *payload, size_t length)
                   {
                     switch (type)
                     {
                     case WStype_DISCONNECTED:
                       M5.Display.println("WS: disconnected");
                       break;
                     case WStype_CONNECTED:
                       M5.Display.printf("WS: connected %s\n", SERVER_PATH);
                       break;
                     case WStype_TEXT:
                      //  M5.Display.printf("WS msg: %.*s\n", (int)length, payload);
                       break;
                     case WStype_BIN:
                     {
                       if (length < sizeof(WsHeader))
                       {
                         M5.Display.println("WS bin too short");
                         break;
                       }

                       WsHeader rx{};
                       memcpy(&rx, payload, sizeof(WsHeader));
                       size_t rx_payload_len = length - sizeof(WsHeader);
                       if (rx_payload_len != rx.payloadBytes)
                       {
                         M5.Display.println("WS payload len mismatch");
                         break;
                       }

                       const uint8_t *body = payload + sizeof(WsHeader);

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
                     } });
  wsClient.setReconnectInterval(2000);
  wsClient.enableHeartbeat(15000, 3000, 2);
}

void loop()
{
  M5.update();
  wsClient.loop();

  if (stateMachine.isIdle())
  {
    M5.Display.setCursor(0, 40);
    M5.Display.println("Hold Btn A: start / Release: stop");

    if (M5.BtnA.wasPressed())
    {
      // TTS 受信・再生状態を初期化
      speaker.reset();

      if (mic.startStreaming())
      {
        M5.Display.println("Streaming...");
        stateMachine.setState(StateMachine::Streaming);
      }
      else
      {
        M5.Display.println("WS not connected (start)");
      }
    }
  }
  else if (stateMachine.isStreaming())
  {
    if (!mic.loop())
    {
      M5.Display.println("WS send failed (data)");
      stateMachine.setState(StateMachine::Idle);
      return;
    }

    // ボタンを離したら残りを送って終了メッセージ
    if (M5.BtnA.wasReleased())
    {
      if (!mic.stopStreaming())
      {
        M5.Display.println("WS send failed (tail/end)");
      }
      stateMachine.setState(StateMachine::Idle);
      M5.Display.println("Stopped. Hold Btn A to start.");

      // 終了直後のTTS再生でMic/Speakerが競合しないよう、少し待つ
      delay(20);
    }
  }

  // ---- Downlink TTS playback (handled by Speaker) ----
  speaker.loop();
}
