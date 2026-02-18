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
#include "../include/speaking.hpp"
#include "../include/listening.hpp"
#include "../include/wake_up_word.hpp"
#include "../include/display.hpp"

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
static Speaking speaking(stateMachine);
static Listening listening(wsClient, stateMachine, SAMPLE_RATE);
static WakeUpWord wakeUpWord(stateMachine, SAMPLE_RATE);
static Display display(stateMachine);

// Protocol types are defined in include/protocols.hpp
namespace
{
bool applyRemoteStateCommand(const uint8_t *body, size_t bodyLen)
{
  if (body == nullptr || bodyLen < 1)
  {
    log_w("StateCmd payload too short: %u", static_cast<unsigned>(bodyLen));
    return false;
  }

  RemoteState target = static_cast<RemoteState>(body[0]);
  switch (target)
  {
  case RemoteState::Idle:
    stateMachine.setState(StateMachine::Idle);
    return true;
  case RemoteState::Listening:
    stateMachine.setState(StateMachine::Listening);
    return true;
  case RemoteState::Thinking:
    stateMachine.setState(StateMachine::Thinking);
    return true;
  case RemoteState::Speaking:
    stateMachine.setState(StateMachine::Speaking);
    return true;
  default:
    log_w("Unknown remote state: %u", static_cast<unsigned>(body[0]));
    return false;
  }
}
} // namespace

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
    // M5.Display.println("WS: disconnected");
    log_i("WS disconnected");
    break;
  case WStype_CONNECTED:
    // M5.Display.printf("WS: connected %s\n", SERVER_PATH);
    log_i("WS connected to %s", SERVER_PATH);
    break;
  case WStype_TEXT:
    //  M5.Display.printf("WS msg: %.*s\n", (int)length, payload);
    break;
  case WStype_BIN:
  {
    if (length < sizeof(WsHeader))
    {
      // M5.Display.println("WS bin too short");
      log_i("WS bin too short: %d", (int)length);
      break;
    }

    WsHeader rx{};
    memcpy(&rx, payload, sizeof(WsHeader));
    size_t rx_payload_len = length - sizeof(WsHeader);
    if (rx_payload_len != rx.payloadBytes)
    {
      // M5.Display.println("WS payload len mismatch");
      log_i("WS payload len mismatch: expected=%u got=%u", (unsigned)rx.payloadBytes, (unsigned)rx_payload_len);
      break;
    }

    const uint8_t *body = payload + sizeof(WsHeader);
    log_i("WS bin kind=%u len=%d", (unsigned)rx.kind, (int)length);

    switch (static_cast<MessageKind>(rx.kind))
    {
    case MessageKind::AudioWav:
      speaking.handleWavMessage(rx, body, rx_payload_len);
      break;
    case MessageKind::StateCmd:
      if (static_cast<MessageType>(rx.messageType) == MessageType::DATA)
      {
        applyRemoteStateCommand(body, rx_payload_len);
      }
      else
      {
        log_w("StateCmd unsupported msgType=%u", static_cast<unsigned>(rx.messageType));
      }
      break;
    default:
      // M5.Display.printf("WS bin kind=%u len=%d\n", (unsigned)rx.kind, (int)length);
      break;
    }

    break;
  }
  default:
    break;
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

  listening.init();
  speaking.init();
  wakeUpWord.init();
  display.init();

  connectWiFi();

  // Mic/Speaking setup
  M5.Speaker.setVolume(200); // 0-255

  wsClient.begin(SERVER_HOST, SERVER_PORT, SERVER_PATH);
  wsClient.onEvent(handleWsEvent);
  wsClient.setReconnectInterval(2000);
  wsClient.enableHeartbeat(15000, 3000, 2);

  // State entry/exit hooks
  stateMachine.addStateEntryEvent(StateMachine::Idle, [](StateMachine::State, StateMachine::State) {
    wakeUpWord.begin();
  });
  stateMachine.addStateExitEvent(StateMachine::Idle, [](StateMachine::State, StateMachine::State) {
    wakeUpWord.end();
  });

  stateMachine.addStateEntryEvent(StateMachine::Listening, [](StateMachine::State, StateMachine::State) {
    listening.begin();
  });
  stateMachine.addStateExitEvent(StateMachine::Listening, [](StateMachine::State, StateMachine::State) {
    listening.end();
  });

  stateMachine.addStateEntryEvent(StateMachine::Speaking, [](StateMachine::State, StateMachine::State) {
    speaking.begin();
  });
  stateMachine.addStateExitEvent(StateMachine::Speaking, [](StateMachine::State, StateMachine::State) {
    speaking.end();
  });

  // initial state setup (Idle)
  wakeUpWord.begin();
}

void loop()
{
  M5.update();
  wsClient.loop();

  StateMachine::State current = stateMachine.getState();
  switch (current)
  {
  case StateMachine::Idle:
    wakeUpWord.loop();
    break;
  case StateMachine::Listening:
    listening.loop();
    break;
  case StateMachine::Thinking:
    // Wait for server side command / audio stream.
    break;
  case StateMachine::Speaking:
    speaking.loop();
    break;
  default:
    break;
  }

  display.loop();
}
