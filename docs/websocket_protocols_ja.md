<!--
コーディングエージェント向け指示: このディレクトリにはプロトコルのみを記述し、CPP、Pythonの実装コードの例を記述する必要はありません。どんなプロトコルが実装されているか確認するために用います。
-->

# WebSocket protobuf プロトコル仕様

このドキュメントは、CoreS3 ファームウェアと Python サーバーがやり取りする WebSocket プロトコルの現行実装をまとめたものです。

現行実装では、1 回の WebSocket binary frame に 1 つの protobuf `WebSocketMessage` を格納します。

## protobuf 定義

- proto file: `protobuf/websocket-message.proto`
- package: `stackchan.websocket.v1`
- top-level message: `WebSocketMessage`

### `WebSocketMessage`

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `kind` | `MessageKind` | メッセージ種別 |
| `message_type` | `MessageType` | `START` / `DATA` / `END` |
| `seq` | `uint32` | 送信側でインクリメントするシーケンス番号 |
| `body` | `oneof` | `kind` / `message_type` に対応する typed body |

### `MessageKind` 一覧

| 名前 | 方向 | 用途 |
| --- | --- | --- |
| `AudioPcm` | CoreS3 → Server | マイク音声 PCM ストリーム |
| `AudioWav` | Server → CoreS3 | TTS 音声 PCM ストリーム |
| `StateCmd` | Server → CoreS3 | 状態遷移指示 |
| `WakeWordEvt` | CoreS3 → Server | ウェイクワード検出通知 |
| `StateEvt` | CoreS3 → Server | 現在状態通知 |
| `SpeakDoneEvt` | CoreS3 → Server | 音声再生完了通知 |
| `ServoCmd` | Server → CoreS3 | サーボ動作シーケンス指示 |
| `ServoDoneEvt` | CoreS3 → Server | サーボ動作完了通知 |

### `MessageType` 一覧

| 名前 | 用途 |
| --- | --- |
| `START` | ストリームまたはセグメント開始 |
| `DATA` | データ本体 |
| `END` | ストリームまたはセグメント終了 |

## マイク入力 `AudioPcm`

- 方向: CoreS3 → Server
- フォーマット: PCM16LE / 16kHz / 1ch
- シーケンス: `AudioPcmStart` → `AudioChunk` 複数回 → `AudioPcmEnd`
- `START` body: `AudioPcmStart {}`
- `DATA` body: `AudioChunk { bytes pcm_bytes; }`
- `END` body: `AudioPcmEnd {}`

### 現行実装メモ

- CoreS3 はマイクを 256 サンプルずつ読み取り、リングバッファに蓄積します。
- `DATA` は `2000 samples` ごとに送信されます。
  - 1 chunk = `2000 samples × 2 bytes = 4000 bytes`
  - 時間長は約 `125 ms`
- 無音判定は平均絶対振幅 `<= 200` が 3 秒継続したときに発火します。
- 停止時は未送信サンプルを `DATA` で flush してから `END` を送ります。

## スピーカ再生 `AudioWav`

- 方向: Server → CoreS3
- 名前は `AudioWav` ですが、実際に送っているのは WAV コンテナではなく PCM16LE ストリームです。
- 1 セグメントの流れは `AudioWavStart` → `AudioChunk` 複数回 → `AudioWavEnd` です。

### body 形式

| messageType | body |
| --- | --- |
- `START` | `AudioWavStart { sample_rate, channels }` |
| `DATA` | `AudioChunk { bytes pcm_bytes; }` |
| `DATA` | `AudioChunk { pcm_bytes }` |
| `END` | `AudioWavEnd {}` |

### 現行実装メモ

- Server は合成済み PCM を約 2 秒単位でセグメント分割します。
- 各 `DATA` chunk は既定で `4096 bytes` です。
- 2 本目のセグメントは約 1 秒後に送信を開始し、その後は 2 秒刻みで続きます。
- CoreS3 は 3 本の受信バッファを持ち、`END` 到達後に `M5.Speaker.playRaw()` で再生します。
- `seq` の欠損は検知しますが、TCP 前提のため再送制御は行いません。

## 状態指示 `StateCmd`

- 方向: Server → CoreS3
- `messageType`: `DATA` のみ
- body: `StateCommand { state }`

利用する状態名:

- `Idle`
- `Listening`
- `Thinking`
- `Speaking`

### 現行実装メモ

- `proxy.listen()` 開始時に Server が `Listening` を指示します。
- 音声 uplink の `END` を受けると、Server は `Thinking` を指示します。
- `proxy.speak()` 完了後、Server は `Idle` を指示します。

## ウェイクワード検出 `WakeWordEvt`

- 方向: CoreS3 → Server
- `messageType`: `DATA` のみ
- body: `WakeWordEvent { detected }`
- `Idle` 中のウェイクワード検出をサーバー側に通知します。
- REST API の `POST /v1/stackchan/{ip}/wakeword` は、このイベントをサーバー内部で擬似発火させます。

## 状態通知 `StateEvt`

- 方向: CoreS3 → Server
- `messageType`: `DATA` のみ
- body: `StateEvent { state }`

利用する状態名:

- `Idle`
- `Listening`
- `Thinking`
- `Speaking`

- CoreS3 は状態遷移の entry hook で送信します。
- WebSocket 切断中は `Disconnected` 状態になりますが、切断時は uplink 送信できないため `StateEvt` では通知されません。

## 発話完了通知 `SpeakDoneEvt`

- 方向: CoreS3 → Server
- `messageType`: `DATA` のみ
- body: `SpeakDoneEvent { done }`
- CoreS3 側の音声再生完了を通知します。
- Server はこの通知を待って `proxy.speak()` を完了させます。

## サーボ動作指示 `ServoCmd`

- 方向: Server → CoreS3
- `messageType`: `DATA` のみ
- body: `ServoCommandSequence { commands }`

### body 構造

- `commands` は最大 255 個まで（`protobuf/websocket-message.options` で nanopb の `max_count:255` を指定）

| 名前 | `ServoCommand` のフィールド |
| --- | --- |
| `Sleep` | `op`, `duration_ms` |
| `MoveX` | `op`, `angle`, `duration_ms` |
| `MoveY` | `op`, `angle`, `duration_ms` |

### 現行実装メモ

- Python 側では 0〜255 個のコマンドをエンコードできます。
- `angle` は signed 8-bit で送られますが、ファームウェアでは最終的に `0..180` 度へ clamp されます。
- `duration_ms <= 0` は即時反映になります。
- 新しい `ServoCmd` を受けると、実行中シーケンスは置き換えられます。

## サーボ動作完了通知 `ServoDoneEvt`

- 方向: CoreS3 → Server
- `messageType`: `DATA` のみ
- body: `ServoDoneEvent { done }`
- 直前に受信したサーボシーケンスの完了通知です。
- Server は `proxy.wait_servo_complete()` でこの完了を待てます。
