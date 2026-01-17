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

//////////////////// 設定 ////////////////////
const char *WIFI_SSID = WIFI_SSID_H;
const char *WIFI_PASS = WIFI_PASSWORD_H;
const char *SERVER_HOST = SERVER_HOST_H;
const int SERVER_PORT = SERVER_PORT_H;
const char *SERVER_PATH = SERVER_PATH_H; // WebSocket エンドポイント
const int SAMPLE_RATE = 16000;           // 16kHz モノラル
/////////////////////////////////////////////

StateMachine stateMachine;

// 0.5 秒ごとに 16kHz * 0.5 = 8,000 サンプルを送る
static constexpr size_t CHUNK_SAMPLES = SAMPLE_RATE / 2; // 8,000 samples ≒ 0.5s
static constexpr size_t MIC_READ_SAMPLES = 256;          // 一度にマイクから読むサンプル数
static constexpr size_t RING_CAPACITY_SAMPLES = SAMPLE_RATE * 2; // 2 秒分のリングバッファ

static int16_t *ring_buffer = nullptr;
static size_t ring_write = 0;
static size_t ring_read = 0;
static size_t ring_available = 0;

static WebSocketsClient wsClient;
static Speaker speaker(stateMachine);

// Protocol types are defined in include/protocols.hpp

static uint16_t seq_counter = 0;

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
  ring_buffer = (int16_t *)heap_caps_malloc(RING_CAPACITY_SAMPLES * sizeof(int16_t), MALLOC_CAP_8BIT);
  memset(ring_buffer, 0, RING_CAPACITY_SAMPLES * sizeof(int16_t));

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

static inline void ringPush(const int16_t *src, size_t samples)
{
  if (samples == 0)
  {
    return;
  }

  // もし追加分がバッファを超えるなら古いデータを捨てる
  if (samples > RING_CAPACITY_SAMPLES)
  {
    src += (samples - RING_CAPACITY_SAMPLES);
    samples = RING_CAPACITY_SAMPLES;
  }

  size_t overflow = (ring_available + samples > RING_CAPACITY_SAMPLES) ? (ring_available + samples - RING_CAPACITY_SAMPLES) : 0;
  if (overflow > 0)
  {
    ring_read = (ring_read + overflow) % RING_CAPACITY_SAMPLES;
    ring_available -= overflow;
  }

  size_t first = std::min(samples, RING_CAPACITY_SAMPLES - ring_write);
  memcpy(ring_buffer + ring_write, src, first * sizeof(int16_t));
  size_t remain = samples - first;
  if (remain > 0)
  {
    memcpy(ring_buffer, src + first, remain * sizeof(int16_t));
  }
  ring_write = (ring_write + samples) % RING_CAPACITY_SAMPLES;
  ring_available += samples;
}

static inline size_t ringPop(int16_t *dst, size_t samples)
{
  size_t to_read = std::min(samples, ring_available);
  if (to_read == 0)
  {
    return 0;
  }

  size_t first = std::min(to_read, RING_CAPACITY_SAMPLES - ring_read);
  memcpy(dst, ring_buffer + ring_read, first * sizeof(int16_t));
  size_t remain = to_read - first;
  if (remain > 0)
  {
    memcpy(dst + first, ring_buffer, remain * sizeof(int16_t));
  }
  ring_read = (ring_read + to_read) % RING_CAPACITY_SAMPLES;
  ring_available -= to_read;
  return to_read;
}

static bool wsConnected()
{
  return (WiFi.status() == WL_CONNECTED) && wsClient.isConnected();
}

static bool sendPacket(MessageType type, const int16_t *samples, size_t sampleCount)
{
  if (!wsConnected())
  {
    return false;
  }

  WsHeader header{};
  header.kind = static_cast<uint8_t>(MessageKind::AudioPcm);
  header.messageType = static_cast<uint8_t>(type);
  header.reserved = 0;
  header.seq = seq_counter++;
  header.payloadBytes = static_cast<uint16_t>(sampleCount * sizeof(int16_t));

  std::vector<uint8_t> packet;
  packet.resize(sizeof(WsHeader) + header.payloadBytes);
  memcpy(packet.data(), &header, sizeof(WsHeader));
  if (header.payloadBytes > 0 && samples != nullptr)
  {
    memcpy(packet.data() + sizeof(WsHeader), samples, header.payloadBytes);
  }

  wsClient.sendBIN(packet.data(), packet.size());
  return true;
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
      ring_available = 0;
      ring_write = 0;
      ring_read = 0;
      seq_counter = 0;

      // TTS 受信・再生状態を初期化
      speaker.reset();

      if (sendPacket(MessageType::START, nullptr, 0))
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
    static int16_t mic_buf[MIC_READ_SAMPLES];
    if (M5.Mic.isEnabled())
    {
      if (M5.Mic.record(mic_buf, MIC_READ_SAMPLES, SAMPLE_RATE))
      {
        ringPush(mic_buf, MIC_READ_SAMPLES);
      }
    }

    // 0.5 秒分たまったら逐次送信
    while (ring_available >= CHUNK_SAMPLES)
    {
      static int16_t send_buf[CHUNK_SAMPLES];
      size_t got = ringPop(send_buf, CHUNK_SAMPLES);
      if (!sendPacket(MessageType::DATA, send_buf, got))
      {
        M5.Display.println("WS send failed (data)");
        stateMachine.setState(StateMachine::Idle);
        return;
      }
    }

    // ボタンを離したら残りを送って終了メッセージ
    if (M5.BtnA.wasReleased())
    {
      if (ring_available > 0)
      {
        static int16_t tail_buf[CHUNK_SAMPLES];
        size_t got = ringPop(tail_buf, ring_available);
        if (!sendPacket(MessageType::DATA, tail_buf, got))
        {
          M5.Display.println("WS send failed (tail)");
          stateMachine.setState(StateMachine::Idle);
          return;
        }
      }
      sendPacket(MessageType::END, nullptr, 0);
      stateMachine.setState(StateMachine::Idle);
      M5.Display.println("Stopped. Hold Btn A to start.");

      // 終了直後のTTS再生でMic/Speakerが競合しないよう、少し待つ
      delay(20);
    }
  }

  // ---- Downlink TTS playback (handled by Speaker) ----
  speaker.loop();
}
