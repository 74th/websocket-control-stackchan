<!--
コーディングエージェント向け指示: このディレクトリにはプロトコルのみを記述し、CPP、Pythonの実装コードの例を記述する必要はありません。どんなプロトコルが実装されているか確認するために用います。
-->

# WebSocket バイナリプロトコル仕様

このドキュメントは、CoreS3 ファームウェアと Python サーバーがやり取りする WebSocket バイナリプロトコルの現行実装をまとめたものです。

## 共通ヘッダ

共通ヘッダ `WsHeader` は `firmware/include/protocols.hpp` で定義されています。

- packed
- little-endian
- 構造: `<B B B H H>`

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `kind` | `uint8` | メッセージ種別 |
| `messageType` | `uint8` | `1=START`, `2=DATA`, `3=END` |
| `reserved` | `uint8` | 現在は常に `0` |
| `seq` | `uint16` | 送信側でインクリメントするシーケンス番号 |
| `payloadBytes` | `uint16` | ヘッダ直後に続く payload のバイト数 |

### `kind` 一覧

| kind | 名前 | 方向 | 用途 |
| --- | --- | --- | --- |
| `1` | `AudioPcm` | CoreS3 → Server | マイク音声 PCM ストリーム |
| `2` | `AudioWav` | Server → CoreS3 | TTS 音声 PCM ストリーム |
| `3` | `StateCmd` | Server → CoreS3 | 状態遷移指示 |
| `4` | `WakeWordEvt` | CoreS3 → Server | ウェイクワード検出通知 |
| `5` | `StateEvt` | CoreS3 → Server | 現在状態通知 |
| `6` | `SpeakDoneEvt` | CoreS3 → Server | 音声再生完了通知 |
| `7` | `ServoCmd` | Server → CoreS3 | サーボ動作シーケンス指示 |
| `8` | `ServoDoneEvt` | CoreS3 → Server | サーボ動作完了通知 |

## `AudioPcm` (`kind=1`)

- 方向: CoreS3 → Server
- フォーマット: PCM16LE / 16kHz / 1ch
- シーケンス: `START` → `DATA` 複数回 → `END`
- `START` payload: なし
- `DATA` payload: PCM16LE 生データ
- `END` payload: 現行ファームウェアではなし

### 現行実装メモ

- CoreS3 はマイクを 256 サンプルずつ読み取り、リングバッファに蓄積します。
- `DATA` は `2000 samples` ごとに送信されます。
  - 1 chunk = `2000 samples × 2 bytes = 4000 bytes`
  - 時間長は約 `125 ms`
- 無音判定は平均絶対振幅 `<= 200` が 3 秒継続したときに発火します。
- 停止時は未送信サンプルを `DATA` で flush してから `END` を送ります。

## `AudioWav` (`kind=2`)

- 方向: Server → CoreS3
- 名前は `AudioWav` ですが、実際に送っているのは WAV コンテナではなく PCM16LE ストリームです。
- 1 セグメントの流れは `START` → `DATA` 複数回 → `END` です。

### payload 形式

| messageType | payload |
| --- | --- |
| `START` | `<uint32 sample_rate><uint16 channels>` |
| `DATA` | PCM16LE 生データ |
| `END` | なし |

### 現行実装メモ

- Server は合成済み PCM を約 2 秒単位でセグメント分割します。
- 各 `DATA` chunk は既定で `4096 bytes` です。
- 2 本目のセグメントは約 1 秒後に送信を開始し、その後は 2 秒刻みで続きます。
- CoreS3 は 3 本の受信バッファを持ち、`END` 到達後に `M5.Speaker.playRaw()` で再生します。
- `seq` の欠損は検知しますが、TCP 前提のため再送制御は行いません。

## `StateCmd` (`kind=3`)

- 方向: Server → CoreS3
- `messageType`: `DATA` のみ
- payload: 1 byte の target state id

| 値 | 状態 |
| --- | --- |
| `0` | `Idle` |
| `1` | `Listening` |
| `2` | `Thinking` |
| `3` | `Speaking` |

### 現行実装メモ

- `proxy.listen()` 開始時に Server が `Listening` を指示します。
- 音声 uplink の `END` を受けると、Server は `Thinking` を指示します。
- `proxy.speak()` 完了後、Server は `Idle` を指示します。

## `WakeWordEvt` (`kind=4`)

- 方向: CoreS3 → Server
- `messageType`: `DATA` のみ
- payload: 1 byte (`1=detected`)
- `Idle` 中のウェイクワード検出をサーバー側に通知します。
- REST API の `POST /v1/stackchan/{ip}/wakeword` は、このイベントをサーバー内部で擬似発火させます。

## `StateEvt` (`kind=5`)

- 方向: CoreS3 → Server
- `messageType`: `DATA` のみ
- payload: 1 byte の current state id

| 値 | 状態 |
| --- | --- |
| `0` | `Idle` |
| `1` | `Listening` |
| `2` | `Thinking` |
| `3` | `Speaking` |

- CoreS3 は状態遷移の entry hook で送信します。
- WebSocket 切断中は `Disconnected` 状態になりますが、切断時は uplink 送信できないため `StateEvt` では通知されません。

## `SpeakDoneEvt` (`kind=6`)

- 方向: CoreS3 → Server
- `messageType`: `DATA` のみ
- payload: 1 byte (`1=done`)
- CoreS3 側の音声再生完了を通知します。
- Server はこの通知を待って `proxy.speak()` を完了させます。

## `ServoCmd` (`kind=7`)

- 方向: Server → CoreS3
- `messageType`: `DATA` のみ
- payload はサーボ動作シーケンス全体です。

### payload 構造

- 先頭 1 byte: `<uint8 command_count>`
- 続いて `command_count` 個のコマンド

| op | 名前 | payload |
| --- | --- | --- |
| `0` | `Sleep` | `<uint8 op><int16 duration_ms>` |
| `1` | `MoveX` | `<uint8 op><int8 angle><int16 duration_ms>` |
| `2` | `MoveY` | `<uint8 op><int8 angle><int16 duration_ms>` |

### 現行実装メモ

- Python 側では 0〜255 個のコマンドをエンコードできます。
- `angle` は signed 8-bit で送られますが、ファームウェアでは最終的に `0..180` 度へ clamp されます。
- `duration_ms <= 0` は即時反映になります。
- 新しい `ServoCmd` を受けると、実行中シーケンスは置き換えられます。

## `ServoDoneEvt` (`kind=8`)

- 方向: CoreS3 → Server
- `messageType`: `DATA` のみ
- payload: 1 byte (`1=done`)
- 直前に受信したサーボシーケンスの完了通知です。
- Server は `proxy.wait_servo_complete()` でこの完了を待てます。
