// Arduino IDE: board = ESP32S3系, ライブラリ: M5Unified, Links2004/WebSocketsClient
// 事前に: Tools→PSRAM有効（SEはPSRAM無しでも動くよう小さめバッファ）

#include <M5Unified.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <algorithm>
#include <cstring>
#include <limits>
#include <vector>
#include "config.h"
#include "../include/metadata.hpp"
#include "../include/protocols.hpp"
#include "../include/state_machine.hpp"
#include "../include/speaking.hpp"
#include "../include/listening.hpp"
#include "../include/wake_up_word.hpp"
#include "../include/display.hpp"
#include "../include/servo.hpp"

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
static BodyServo servo;

// Protocol types are defined in include/protocols.hpp
namespace
{
uint32_t g_uplink_seq = 0;
uint32_t g_last_comm_ms = 0;
constexpr uint32_t kCommTimeoutMs = 60000;
constexpr int kToneChannel = 1;
stackchan_websocket_v1_WebSocketMessage g_tx_message = stackchan_websocket_v1_WebSocketMessage_init_zero;
stackchan_websocket_v1_WebSocketMessage g_rx_message = stackchan_websocket_v1_WebSocketMessage_init_zero;
bool g_tone_playing = false;
bool g_tone_restore_state_pending = false;
StateMachine::State g_tone_restore_state = StateMachine::Idle;

void markCommunicationActive()
{
  g_last_comm_ms = millis();
}

void handleCommunicationTimeout()
{
  if (g_last_comm_ms == 0)
  {
    return;
  }

  uint32_t elapsed = millis() - g_last_comm_ms;
  StateMachine::State current = stateMachine.getState();
  if (elapsed >= kCommTimeoutMs &&
      (current == StateMachine::Thinking || current == StateMachine::Speaking))
  {
    log_w("Communication timeout in state=%u; forcing Idle", static_cast<unsigned>(current));
    stateMachine.setState(StateMachine::Idle);
    markCommunicationActive();
  }
}

bool sendUplinkMessage(const stackchan_websocket_v1_WebSocketMessage &message)
{
  if ((WiFi.status() != WL_CONNECTED) || !wsClient.isConnected())
  {
    return false;
  }

  std::vector<uint8_t> packet;
  if (!encodeWebSocketMessage(message, packet))
  {
    return false;
  }

  wsClient.sendBIN(packet.data(), packet.size());
  markCommunicationActive();
  return true;
}

void appendInt16Le(std::vector<uint8_t> &payload, int16_t value)
{
  size_t start = payload.size();
  payload.resize(start + sizeof(value));
  memcpy(payload.data() + start, &value, sizeof(value));
}

void notifyWakeWordDetected()
{
  auto &message = g_tx_message;
  message = stackchan_websocket_v1_WebSocketMessage_init_zero;
  message.kind = stackchan_websocket_v1_MessageKind_MESSAGE_KIND_WAKE_WORD_EVT;
  message.message_type = stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA;
  message.seq = g_uplink_seq++;
  message.which_body = stackchan_websocket_v1_WebSocketMessage_wake_word_evt_tag;
  message.body.wake_word_evt.detected = true;
  if (!sendUplinkMessage(message))
  {
    log_w("Failed to send WakeWordEvt");
  }
}

void notifyFirmwareMetadata()
{
  auto &message = g_tx_message;
  setFirmwareMetadataMessage(message, g_uplink_seq++);
  if (!sendUplinkMessage(message))
  {
    log_w("Failed to send FirmwareMetadata");
  }
}

void notifyCurrentState(StateMachine::State state)
{
  auto &message = g_tx_message;
  message = stackchan_websocket_v1_WebSocketMessage_init_zero;
  message.kind = stackchan_websocket_v1_MessageKind_MESSAGE_KIND_STATE_EVT;
  message.message_type = stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA;
  message.seq = g_uplink_seq++;
  message.which_body = stackchan_websocket_v1_WebSocketMessage_state_evt_tag;
  message.body.state_evt.state = static_cast<stackchan_websocket_v1_StackchanState>(static_cast<uint8_t>(state));
  if (!sendUplinkMessage(message))
  {
    log_w("Failed to send StateEvt state=%u", static_cast<unsigned>(state));
  }
}

void notifySpeakDone()
{
  auto &message = g_tx_message;
  message = stackchan_websocket_v1_WebSocketMessage_init_zero;
  message.kind = stackchan_websocket_v1_MessageKind_MESSAGE_KIND_SPEAK_DONE_EVT;
  message.message_type = stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA;
  message.seq = g_uplink_seq++;
  message.which_body = stackchan_websocket_v1_WebSocketMessage_speak_done_evt_tag;
  message.body.speak_done_evt.done = true;
  if (!sendUplinkMessage(message))
  {
    log_w("Failed to send SpeakDoneEvt");
  }
}

void notifyServoDone()
{
  auto &message = g_tx_message;
  message = stackchan_websocket_v1_WebSocketMessage_init_zero;
  message.kind = stackchan_websocket_v1_MessageKind_MESSAGE_KIND_SERVO_DONE_EVT;
  message.message_type = stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA;
  message.seq = g_uplink_seq++;
  message.which_body = stackchan_websocket_v1_WebSocketMessage_servo_done_evt_tag;
  message.body.servo_done_evt.done = true;
  if (!sendUplinkMessage(message))
  {
    log_w("Failed to send ServoDoneEvt");
  }
}

void notifyToneDone()
{
  auto &message = g_tx_message;
  message = stackchan_websocket_v1_WebSocketMessage_init_zero;
  message.kind = stackchan_websocket_v1_MessageKind_MESSAGE_KIND_TONE_DONE_EVT;
  message.message_type = stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA;
  message.seq = g_uplink_seq++;
  message.which_body = stackchan_websocket_v1_WebSocketMessage_tone_done_evt_tag;
  message.body.tone_done_evt.done = true;
  if (!sendUplinkMessage(message))
  {
    log_w("Failed to send ToneDoneEvt");
  }
}

bool applyRemoteStateCommand(const stackchan_websocket_v1_StateCommand &command)
{
  switch (command.state)
  {
  case stackchan_websocket_v1_StackchanState_STACKCHAN_STATE_IDLE:
    listening.setFixedDurationMs(0);
    stateMachine.setState(StateMachine::Idle);
    return true;
  case stackchan_websocket_v1_StackchanState_STACKCHAN_STATE_LISTENING:
    listening.setFixedDurationMs(command.listening_duration_ms);
    stateMachine.setState(StateMachine::Listening);
    return true;
  case stackchan_websocket_v1_StackchanState_STACKCHAN_STATE_THINKING:
    listening.setFixedDurationMs(0);
    stateMachine.setState(StateMachine::Thinking);
    return true;
  case stackchan_websocket_v1_StackchanState_STACKCHAN_STATE_SPEAKING:
    listening.setFixedDurationMs(0);
    stateMachine.setState(StateMachine::Speaking);
    return true;
  default:
    log_w("Unknown remote state");
    return false;
  }
}

bool applyServoCommand(const stackchan_websocket_v1_ServoCommandSequence &sequence)
{
  if (sequence.commands_count > kProtoServoCommandMaxCount)
  {
    log_w("ServoCmd count too large: %u", static_cast<unsigned>(sequence.commands_count));
    return false;
  }

  std::vector<uint8_t> payload;
  payload.reserve(1 + sequence.commands_count * 4);
  payload.push_back(static_cast<uint8_t>(sequence.commands_count));

  for (pb_size_t i = 0; i < sequence.commands_count; ++i)
  {
    const auto &command = sequence.commands[i];
    const auto op = command.op;

    if (command.duration_ms < std::numeric_limits<int16_t>::min() ||
        command.duration_ms > std::numeric_limits<int16_t>::max())
    {
      log_w("ServoCmd duration out of range at command=%u", static_cast<unsigned>(i));
      return false;
    }

    payload.push_back(static_cast<uint8_t>(op));
    if (op == stackchan_websocket_v1_ServoOperation_SERVO_OPERATION_SLEEP)
    {
      appendInt16Le(payload, static_cast<int16_t>(command.duration_ms));
      continue;
    }

    if (command.angle < std::numeric_limits<int8_t>::min() ||
        command.angle > std::numeric_limits<int8_t>::max())
    {
      log_w("ServoCmd angle out of range at command=%u", static_cast<unsigned>(i));
      return false;
    }

    payload.push_back(static_cast<uint8_t>(static_cast<int8_t>(command.angle)));
    appendInt16Le(payload, static_cast<int16_t>(command.duration_ms));
  }

  if (!servo.enqueueSequence(payload.data(), payload.size()))
  {
    log_w("Failed to apply servo command");
    return false;
  }
  return true;
}

bool applyToneCommand(const stackchan_websocket_v1_ToneCommand &command)
{
  if (command.frequency <= 0.0f)
  {
    log_w("ToneCmd frequency must be positive");
    return false;
  }
  if (command.duration_ms == 0)
  {
    log_w("ToneCmd duration must be positive");
    return false;
  }

  StateMachine::State previous_state = stateMachine.getState();
  if (previous_state != StateMachine::Speaking)
  {
    g_tone_restore_state = previous_state;
    g_tone_restore_state_pending = true;
    stateMachine.setState(StateMachine::Speaking);
  }
  else
  {
    g_tone_restore_state_pending = false;
  }

  if (!M5.Speaker.tone(command.frequency, command.duration_ms, kToneChannel, true))
  {
    if (g_tone_restore_state_pending)
    {
      stateMachine.setState(g_tone_restore_state);
      g_tone_restore_state_pending = false;
    }
    log_w(
        "Failed to start tone frequency=%.1f duration=%lu",
        command.frequency,
        static_cast<unsigned long>(command.duration_ms));
    return false;
  }

  g_tone_playing = true;
  return true;
}

void pollTonePlayback()
{
  if (!g_tone_playing)
  {
    return;
  }

  if (M5.Speaker.isPlaying(kToneChannel) != 0)
  {
    return;
  }

  g_tone_playing = false;
  if (g_tone_restore_state_pending)
  {
    stateMachine.setState(g_tone_restore_state);
    g_tone_restore_state_pending = false;
  }
  notifyToneDone();
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
    resetServerMetadata();
    stateMachine.setState(StateMachine::Disconnected);
    break;
  case WStype_CONNECTED:
    // M5.Display.printf("WS: connected %s\n", SERVER_PATH);
    log_i("WS connected to %s", SERVER_PATH);
    if (stateMachine.getState() == StateMachine::Disconnected)
    {
      stateMachine.setState(StateMachine::Idle);
    }
    markCommunicationActive();
    notifyFirmwareMetadata();
    notifyCurrentState(stateMachine.getState());
    break;
  case WStype_TEXT:
    //  M5.Display.printf("WS msg: %.*s\n", (int)length, payload);
    markCommunicationActive();
    break;
  case WStype_BIN:
  {
    markCommunicationActive();
    auto &rx = g_rx_message;
    rx = stackchan_websocket_v1_WebSocketMessage_init_zero;
    if (!decodeWebSocketMessage(payload, length, rx))
    {
      log_i("WS protobuf decode failed: %d", (int)length);
      break;
    }

    log_i("WS protobuf kind=%u len=%d", (unsigned)rx.kind, (int)length);

    switch (rx.kind)
    {
    case stackchan_websocket_v1_MessageKind_MESSAGE_KIND_AUDIO_WAV:
    {
      if (rx.message_type == stackchan_websocket_v1_MessageType_MESSAGE_TYPE_START &&
          rx.which_body == stackchan_websocket_v1_WebSocketMessage_audio_wav_start_tag)
      {
        speaking.handleWavStart(
            rx.seq,
            rx.body.audio_wav_start.sample_rate,
            static_cast<uint16_t>(rx.body.audio_wav_start.channels));
      }
      else if (rx.message_type == stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA &&
               rx.which_body == stackchan_websocket_v1_WebSocketMessage_audio_wav_data_tag)
      {
        size_t body_len = getProtoAudioChunkSize(rx.body.audio_wav_data);
        speaking.handleWavData(rx.seq, getProtoAudioChunkBytes(rx.body.audio_wav_data), body_len);
      }
      else if (rx.message_type == stackchan_websocket_v1_MessageType_MESSAGE_TYPE_END &&
               rx.which_body == stackchan_websocket_v1_WebSocketMessage_audio_wav_end_tag)
      {
        speaking.handleWavEnd(rx.seq);
      }
      else
      {
        log_w("AudioWav protobuf body mismatch type=%u body=%u", (unsigned)rx.message_type, (unsigned)rx.which_body);
      }
      break;
    }
    case stackchan_websocket_v1_MessageKind_MESSAGE_KIND_STATE_CMD:
      if (rx.message_type == stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA &&
          rx.which_body == stackchan_websocket_v1_WebSocketMessage_state_cmd_tag)
      {
        applyRemoteStateCommand(rx.body.state_cmd);
      }
      else
      {
        log_w("StateCmd protobuf body mismatch type=%u body=%u", (unsigned)rx.message_type, (unsigned)rx.which_body);
      }
      break;
    case stackchan_websocket_v1_MessageKind_MESSAGE_KIND_SERVO_CMD:
      if (rx.message_type == stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA &&
          rx.which_body == stackchan_websocket_v1_WebSocketMessage_servo_cmd_tag)
      {
        applyServoCommand(rx.body.servo_cmd);
      }
      else
      {
        log_w("ServoCmd protobuf body mismatch type=%u body=%u", (unsigned)rx.message_type, (unsigned)rx.which_body);
      }
      break;
    case stackchan_websocket_v1_MessageKind_MESSAGE_KIND_TONE_CMD:
      if (rx.message_type == stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA &&
          rx.which_body == stackchan_websocket_v1_WebSocketMessage_tone_cmd_tag)
      {
        applyToneCommand(rx.body.tone_cmd);
      }
      else
      {
        log_w("ToneCmd protobuf body mismatch type=%u body=%u", (unsigned)rx.message_type, (unsigned)rx.which_body);
      }
      break;
    case stackchan_websocket_v1_MessageKind_MESSAGE_KIND_SERVER_METADATA:
      if (rx.message_type == stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA &&
          rx.which_body == stackchan_websocket_v1_WebSocketMessage_server_metadata_tag)
      {
        applyServerMetadata(rx.body.server_metadata);
        if (stateMachine.getState() == StateMachine::Idle)
        {
          if (shouldUseDeviceWakeWord())
          {
            wakeUpWord.begin();
          }
          else
          {
            wakeUpWord.end();
          }
        }
      }
      else
      {
        log_w("ServerMetadata protobuf body mismatch type=%u body=%u", (unsigned)rx.message_type, (unsigned)rx.which_body);
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
#if defined(ARDUINO_M5STACK_ATOMS3R)
  cfg.external_speaker.atomic_echo = 1;
#endif
#if defined(ARDUINO_ATOM_ECHOS3R)
  cfg.internal_mic = true;
#endif
  M5.begin(cfg);
  auto mic_cfg = M5.Mic.config();
  mic_cfg.sample_rate = SAMPLE_RATE;
  mic_cfg.dma_buf_len = 256;
  mic_cfg.stereo = false;
  // mic_cfg.over_sampling = 4;
  M5.Mic.config(mic_cfg);

  listening.init();
  speaking.init();
  speaking.setSpeakFinishedCallback([]() {
    notifySpeakDone();
  });
  servo.init();
  servo.setCompletionCallback([]() {
    notifyServoDone();
  });
  wakeUpWord.init();
  wakeUpWord.setWakeWordDetectedCallback([]() {
    notifyWakeWordDetected();
  });
  display.init();
  initializeFirmwareMetadata();

  connectWiFi();

  // Mic/Speaking setup
  M5.Speaker.setVolume(200); // 0-255

  wsClient.begin(SERVER_HOST, SERVER_PORT, SERVER_PATH);
  markCommunicationActive();
  wsClient.onEvent(handleWsEvent);
  wsClient.setReconnectInterval(2000);
  wsClient.enableHeartbeat(15000, 3000, 2);

  // State entry/exit hooks
  stateMachine.addStateEntryEvent(StateMachine::Idle, [](StateMachine::State, StateMachine::State) {
    notifyCurrentState(StateMachine::Idle);
    if (shouldUseDeviceWakeWord())
    {
      wakeUpWord.begin();
    }
  });
  stateMachine.addStateExitEvent(StateMachine::Idle, [](StateMachine::State, StateMachine::State) {
    wakeUpWord.end();
  });

  stateMachine.addStateEntryEvent(StateMachine::Listening, [](StateMachine::State, StateMachine::State) {
    notifyCurrentState(StateMachine::Listening);
    listening.begin();
  });
  stateMachine.addStateExitEvent(StateMachine::Listening, [](StateMachine::State, StateMachine::State) {
    listening.end();
  });

  stateMachine.addStateEntryEvent(StateMachine::Speaking, [](StateMachine::State, StateMachine::State) {
    notifyCurrentState(StateMachine::Speaking);
    speaking.begin();
  });
  stateMachine.addStateExitEvent(StateMachine::Speaking, [](StateMachine::State, StateMachine::State) {
    speaking.end();
  });

  stateMachine.addStateEntryEvent(StateMachine::Thinking, [](StateMachine::State, StateMachine::State) {
    notifyCurrentState(StateMachine::Thinking);
  });
}

void loop()
{
  M5.update();
  wsClient.loop();
  handleCommunicationTimeout();
  servo.loop();
  pollTonePlayback();

  StateMachine::State current = stateMachine.getState();
  switch (current)
  {
  case StateMachine::Idle:
    if (shouldUseDeviceWakeWord())
    {
      wakeUpWord.loop();
    }
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
  case StateMachine::Disconnected:
    // Wait for WS reconnect.
    break;
  default:
    break;
  }

  display.loop();
}
