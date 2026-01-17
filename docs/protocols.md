# プロトコル仕様

このドキュメントは、本リポジトリで使われている WebSocket ベースのバイナリプロトコルについて日本語で説明します。

主に CoreS3（ESP32）とサーバー間でやり取りされる音声ストリーミングおよびダウンロード用のメッセージを定義します。

## 音声ストリーム出力（PCM1 / WAV1）

### 概要

- 方向: クライアント -> サーバ
- 音声ストリーム: PCM16LE（モノラル）を WebSocket のバイナリメッセージで送受信します。
- 主要プロトコル種別:
  - `PCM1`: クライアント（CoreS3）→サーバーの音声アップロード用ヘッダ
  - `WAV1`: サーバー→クライアントの TTS / WAV チャンク配信用ヘッダ（簡易説明）

### PCM1 ヘッダ（WsAudioHeader）

C++ での構造体定義（`include/protocols.hpp` に保持）:

```cpp
struct __attribute__((packed)) WsAudioHeader
{
  char kind[4];        // "PCM1"
  uint8_t messageType; // MessageType (1=START, 2=DATA, 3=END)
  uint8_t reserved;    // 予約領域（0）
  uint16_t seq;        // シーケンス番号（リトルエンディアン）
  uint32_t sampleRate; // サンプルレート（例: 16000）
  uint16_t channels;   // チャンネル数（通常 1）
  uint16_t payloadBytes; // ヘッダの直後に続く PCM バイト数
};
```

- バイトオーダー: リトルエンディアンを前提とします。
- `messageType`:
  - 1 (START): 録音・送信開始を示します。通常 `payloadBytes` は 0。
  - 2 (DATA): PCM データが続くことを示します。`payloadBytes` はデータ長バイト数。
  - 3 (END): 録音・送信終了を示します。通常 `payloadBytes` は 0。

#### 実装上の注意

- `kind` フィールドは 4 バイト固定の ASCII マジックです。現在は "PCM1" を使いますが、将来別種のペイロード（たとえば別コーデックや制御メッセージ）を導入することを想定して他の値を追加できます。
- `seq` は送信側でインクリメントします。これによりパケットの並び確認や再送判定等に利用できます。
- `payloadBytes` はヘッダ直後に続く生の PCM バイト数（PCM16LE の場合は 2 の倍数）です。

### WAV1（サーバー→クライアント、TTS 送信）の簡易仕様

サーバーは分割された WAV バイナリをクライアントに送り返すときに、`WAV1` マジックを先頭に置いた独自チャンクメッセージを送ります（`src/main.cpp` の WS BIN ハンドラ参照）。

レイアウト（簡易）:
- 4 bytes: b"WAV1"
- 4 bytes: uint32 total_bytes（送信予定の合計バイト数、LE）
- 4 bytes: uint32 offset（このチャンクのオフセット、LE）
- N bytes: payload（offset からの chunk データ）

サーバーは複数チャンクに分けて送り、クライアントは offset と total を使って受信と結合を行います。
