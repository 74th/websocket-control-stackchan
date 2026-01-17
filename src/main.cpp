// Arduino IDE: board = ESP32S3系, ライブラリ: M5Unified, Links2004/WebSocketsClient
// 事前に: Tools→PSRAM有効（SEはPSRAM無しでも動くよう小さめバッファ）

#include <M5Unified.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <algorithm>
#include <cstring>
#include <vector>
#include "config.h"

//////////////////// 設定 ////////////////////
const char *WIFI_SSID = WIFI_SSID_H;
const char *WIFI_PASS = WIFI_PASSWORD_H;
const char *SERVER_HOST = SERVER_HOST_H;
const int SERVER_PORT = SERVER_PORT_H;
const char *SERVER_PATH = SERVER_PATH_H; // WebSocket エンドポイント
const int SAMPLE_RATE = 16000;           // 16kHz モノラル
/////////////////////////////////////////////

#define STATE_IDLE 0
#define STATE_STREAMING 1

uint8_t state = STATE_IDLE;

// 0.5 秒ごとに 16kHz * 0.5 = 8,000 サンプルを送る
static constexpr size_t CHUNK_SAMPLES = SAMPLE_RATE / 2; // 8,000 samples ≒ 0.5s
static constexpr size_t MIC_READ_SAMPLES = 256;          // 一度にマイクから読むサンプル数
static constexpr size_t RING_CAPACITY_SAMPLES = SAMPLE_RATE * 2; // 2 秒分のリングバッファ

static int16_t *ring_buffer = nullptr;
static size_t ring_write = 0;
static size_t ring_read = 0;
static size_t ring_available = 0;

// Downlink TTS WAV assembly
static std::vector<uint8_t> tts_buffer;
static uint32_t tts_expected = 0;
static uint32_t tts_received = 0;
static bool tts_ready_to_play = false;
static bool tts_playing = false;
static bool tts_mic_was_enabled = false;

static WebSocketsClient wsClient;

enum class MessageType : uint8_t
{
  START = 1,
  DATA = 2,
  END = 3,
};

struct __attribute__((packed)) WsAudioHeader
{
  char kind[4];        // "PCM1"
  uint8_t messageType; // MessageType
  uint8_t reserved;    // 0
  uint16_t seq;        // sequence number
  uint32_t sampleRate; // LE
  uint16_t channels;   // 1
  uint16_t payloadBytes; // PCM payload bytes following the header
};

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
                       if (length >= 12 && memcmp(payload, "WAV1", 4) == 0)
                       {
                         uint32_t total = 0;
                         uint32_t offset = 0;
                         memcpy(&total, payload + 4, sizeof(uint32_t));
                         memcpy(&offset, payload + 8, sizeof(uint32_t));
                         size_t chunk_len = length - 12;

                         if (total == 0 || offset + chunk_len > total)
                         {
                           M5.Display.println("Invalid WAV chunk header");
                           log_e("Invalid chunk hdr: total=%lu offset=%lu chunk=%u len=%u", (unsigned long)total, (unsigned long)offset, (unsigned)chunk_len, (unsigned)length);
                           break;
                         }

                         // 新規ストリーム開始
                         if (offset == 0 || total != tts_expected)
                         {
                           tts_buffer.assign(total, 0);
                           tts_expected = total;
                           tts_received = 0;
                           tts_ready_to_play = false;
                           tts_playing = false;
                           M5.Display.printf("Recv TTS total=%u bytes\n", (unsigned)total);
                           log_i("TTS start total=%lu", (unsigned long)total);
                         }

                         if (offset != tts_received)
                         {
                           M5.Display.println("Unexpected WAV offset, dropping");
                           log_e("Unexpected offset: got=%lu expected=%lu", (unsigned long)offset, (unsigned long)tts_received);
                           tts_expected = 0;
                           tts_received = 0;
                           tts_buffer.clear();
                           break;
                         }

                         memcpy(tts_buffer.data() + offset, payload + 12, chunk_len);
                         tts_received += chunk_len;
                         log_d("TTS chunk offset=%lu size=%u recv=%lu/%lu", (unsigned long)offset, (unsigned)chunk_len, (unsigned long)tts_received, (unsigned long)tts_expected);

                         if (tts_received >= tts_expected)
                         {
                           M5.Display.printf("TTS ready: %u bytes\n", (unsigned)tts_expected);
                           log_i("TTS ready total=%lu", (unsigned long)tts_expected);
                           tts_ready_to_play = true;
                         }
                       }
                       else
                       {
                         M5.Display.printf("WS bin len: %d\n", (int)length);
                       }
                       break;
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

  WsAudioHeader header{};
  memcpy(header.kind, "PCM1", 4);
  header.messageType = static_cast<uint8_t>(type);
  header.reserved = 0;
  header.seq = seq_counter++;
  header.sampleRate = static_cast<uint32_t>(SAMPLE_RATE);
  header.channels = 1;
  header.payloadBytes = static_cast<uint16_t>(sampleCount * sizeof(int16_t));

  std::vector<uint8_t> packet;
  packet.resize(sizeof(WsAudioHeader) + header.payloadBytes);
  memcpy(packet.data(), &header, sizeof(WsAudioHeader));
  if (header.payloadBytes > 0 && samples != nullptr)
  {
    memcpy(packet.data() + sizeof(WsAudioHeader), samples, header.payloadBytes);
  }

  wsClient.sendBIN(packet.data(), packet.size());
  return true;
}

void loop()
{
  M5.update();
  wsClient.loop();

  if (state == STATE_IDLE)
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
      tts_buffer.clear();
      tts_expected = 0;
      tts_received = 0;
      tts_ready_to_play = false;
      tts_playing = false;

      if (sendPacket(MessageType::START, nullptr, 0))
      {
        M5.Display.println("Streaming...");
        state = STATE_STREAMING;
      }
      else
      {
        M5.Display.println("WS not connected (start)");
      }
    }
  }
  else if (state == STATE_STREAMING)
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
        state = STATE_IDLE;
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
          state = STATE_IDLE;
          return;
        }
      }
      sendPacket(MessageType::END, nullptr, 0);
      state = STATE_IDLE;
      M5.Display.println("Stopped. Hold Btn A to start.");

      // 終了直後のTTS再生でMic/Speakerが競合しないよう、少し待つ
      delay(20);
    }
  }

  // ---- Downlink TTS playback (deferred from WS callback) ----
  if (tts_ready_to_play && !tts_playing)
  {
    if (tts_buffer.empty())
    {
      tts_ready_to_play = false;
      return;
    }
    M5.Speaker.stop();
    M5.Display.println("Playing TTS...");
    tts_mic_was_enabled = M5.Mic.isEnabled();
    if (tts_mic_was_enabled)
    {
      M5.Mic.end();
      log_i("Mic stopped for TTS playback");
      delay(10);
    }

    log_i("TTS play start size=%u", (unsigned)tts_buffer.size());
    M5.Speaker.playWav(tts_buffer.data(), tts_buffer.size());
    tts_playing = true;
    tts_ready_to_play = false;
  }

  if (tts_playing && !M5.Speaker.isPlaying())
  {
    log_i("TTS play done");
    M5.Speaker.stop();
    M5.Speaker.end();
    delay(10);
    tts_buffer.clear();
    tts_expected = 0;
    tts_received = 0;
    tts_playing = false;
    M5.Display.println("TTS done.");

    if (tts_mic_was_enabled && !M5.Mic.isEnabled())
    {
      M5.Mic.begin();
      log_i("Mic restarted after TTS playback");
    }
  }
}
