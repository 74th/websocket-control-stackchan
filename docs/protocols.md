<!--
コーディングエージェント向け指示: このディレクトリにはプロトコルのみを記述し、CPP、Pythonの実装コードの例を記述する必要はありません。どんなプロトコルが実装されているか確認するために用います。
-->

# プロトコル仕様（1 バイト kind / 共通ヘッダ）

このドキュメントは、本リポジトリで使われている WebSocket ベースのバイナリプロトコルについて日本語で説明します。CoreS3（ESP32）とサーバー間の送受信で共通のヘッダを使います。

## 共通ヘッダ: WsHeader

`include/protocols.hpp` に定義されるヘッダ（packed, LE）:

```cpp
enum class MessageKind : uint8_t {
  AudioPcm = 1, // クライアント→サーバ（PCM16LE）
  AudioWav = 2, // サーバ→クライアント（WAV バイト列）
  StateCmd = 3, // サーバ→クライアント（状態遷移指示）
};

enum class MessageType : uint8_t {
  START = 1,
  DATA = 2,
  END  = 3,
};

struct __attribute__((packed)) WsHeader {
  uint8_t  kind;         // MessageKind
  uint8_t  messageType;  // MessageType
  uint8_t  reserved;     // 0（将来のフラグ用）
  uint16_t seq;          // シーケンス番号
  uint16_t payloadBytes; // ヘッダ直後に続くバイト数
};
```

- バイトオーダー: リトルエンディアン。
- `seq`: 送信側がインクリメント。整合チェックに使用。
- `payloadBytes`: ヘッダ直後に続く生データ長（最大 65535）。

### Uplink: kind = AudioPcm (1)

- 方向: クライアント -> サーバ
- フォーマット: PCM16LE モノラル、サンプルレート固定 16 kHz（チャンネル数 1）。
- メッセージの流れ: START (通常 payload 0) → DATA 複数回 → END (payload 0 または残りを含む)。
- サーバー側は固定パラメータ（16 kHz / ch=1）として WAV に保存し、STT に渡す。

### Downlink: kind = AudioWav (2)

- 方向: サーバ -> クライアント
- コンテンツ: PCM16LE を「総サイズなし」でストリーミング分割送信。
- メッセージの流れ:
  - START: payload は `<uint32 sample_rate><uint16 channels>`。
  - DATA: payload に PCM データチャンク（サイズは適宜分割）。
  - END: payload 0。クライアントは受信完了として再生を開始する。
- クライアントは START でバッファを初期化し、DATA を順次 append、END で再生。seq で欠損検知は可能（TCP 前提なら警告のみで継続も可）。

### Downlink: kind = StateCmd (3)

- 方向: サーバ -> クライアント
- メッセージ種別: `DATA` のみ使用
- payload: 1 byte の target state id
  - `0=Idle`
  - `1=Listening`
  - `2=Thinking`
  - `3=Speaking`
- 現行運用: uplink の `END` 受信完了直後に `Thinking` を送信。

### kind の拡張例

- AudioPcm (1): 現行の PCM16LE アップリンク
- AudioWav (2): WAV ダウンリンク
- StateCmd (3): 状態遷移指示
- 予約: 4 以降を将来のコーデック / 制御用に確保

### 簡易バイト例（AudioPcm / DATA）

- kind: 0x01
- messageType: DATA (0x02)
- reserved: 0x00
- seq: 0x0005 (LE => 0x05 0x00)
- payloadBytes: 0x4000 (16384 バイトの PCM)
- body: 16384 バイトの PCM16LE データ
