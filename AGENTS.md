# AGENTS 概要

本リポジトリの現行実装を素早く把握するためのメモです。詳細仕様は `docs/protocols.md` と `docs/rest-api.md` を参照してください。

## 全体像

- CoreS3 側は `firmware/`、Python サーバー側は `stackchan_server/`。
- 音声 uplink は `AudioPcm`、音声 downlink は `AudioWav`（実体は raw PCM）。
- サーバーは FastAPI を公開し、WebSocket と REST API の両方を持つ。
- サーボ制御が追加済みで、WebSocket プロトコルには `ServoCmd` / `ServoDoneEvt` がある。

## 状態遷移の要点

- ファームウェア状態: `Idle`, `Listening`, `Thinking`, `Speaking`, `Disconnected`
- サーバーから指示できるのは `StateCmd` の `0..3` (`Idle`〜`Speaking`)
- `Disconnected` はファームウェア内部状態で、WebSocket 切断時に入る
- `WakeWordEvt` を受けるか、REST API の wakeword 擬似発火で talk session が始まる

## WebSocket プロトコル要約

- 共通ヘッダ: `WsHeader` (`<B B B H H>`, packed, little-endian)
- `kind`
  - `1=AudioPcm`
  - `2=AudioWav`
  - `3=StateCmd`
  - `4=WakeWordEvt`
  - `5=StateEvt`
  - `6=SpeakDoneEvt`
  - `7=ServoCmd`
  - `8=ServoDoneEvt`
- `messageType`
  - `1=START`
  - `2=DATA`
  - `3=END`

### 現行挙動

- `AudioPcm`
  - PCM16LE / 16kHz / 1ch
  - `START -> DATA* -> END`
  - `DATA` は 2000 samples（4000 bytes, 約 125ms）ごと
  - 無音 3 秒で自動終了
- `AudioWav`
  - 名前に反して WAV コンテナではなく PCM ストリーム
  - `START` payload は `<uint32 sample_rate><uint16 channels>`
  - `DATA` chunk は既定 4096 bytes
  - 約 2 秒セグメントで送信し、2 本目は約 1 秒後に先行開始
- `ServoCmd`
  - payload: `<uint8 count><commands...>`
  - op: `0=Sleep`, `1=MoveX`, `2=MoveY`
  - 新規コマンド受信時は実行中シーケンスを置き換える

## サーバー側 (`stackchan_server/`)

### `stackchan_server/app.py`

- `GET /health`
- `WS /ws/stackchan`
- `GET /v1/stackchan`
- `GET /v1/stackchan/{stackchan_ip}`
- `POST /v1/stackchan/{stackchan_ip}/wakeword`
- `POST /v1/stackchan/{stackchan_ip}/speak`

### `stackchan_server/ws_proxy.py`

- 接続ごとに `WsProxy` を作成
- `websocket.client.host` を StackChan の識別子として使う
- 同一 IP の再接続時は既存接続を置き換える
- `listen()` は `Listening` 指示後、音声 uplink 完了を待つ
- `speak()` は TTS downlink 送信後、`SpeakDoneEvt` を待つ
- `move_servo()` / `wait_servo_complete()` を公開

### 音声認識 / 音声合成

- 既定 STT: `GoogleCloudSpeechToText`（ストリーミング認識）
- 既定 TTS: `VoiceVoxSpeechSynthesizer`
- `example_apps/echo.py` / `echo_with_move.py` は `STACKCHAN_WHISPER_MODEL` があると `whisper.cpp` を使う
- `DEBUG_RECODING=1` のときのみ録音 WAV と TTS WAV を `stackchan_server/recordings/` に保存する
  - 実装上この変数名は typo のまま

## ファームウェア側 (`firmware/`)

- `src/main.cpp`
  - Wi-Fi 接続後、`/ws/stackchan` に接続
  - `AudioWav`, `StateCmd`, `ServoCmd` を受信処理
  - 通信が 60 秒止まると `Thinking` / `Speaking` から `Idle` に戻す
- `src/listening.cpp`
  - マイク読み取り 256 サンプル単位
  - 2 秒リングバッファ
  - 無音 3 秒で停止
- `src/speaking.cpp`
  - 3 本バッファで TTS セグメント受信
  - `END` 後に `M5.Speaker.playRaw()` で再生
  - 再生完了時に `SpeakDoneEvt`
- `src/servo.cpp`
  - `ServoCmd` を非同期実行
  - `MoveX`, `MoveY`, `Sleep` を順次処理
  - 完了時に `ServoDoneEvt`
- `src/display.cpp`
  - `Idle=濃いグレー`, `Listening=青`, `Thinking=オレンジ`, `Speaking=緑`, `Disconnected=赤`

## サンプルアプリ

- `example_apps/echo.py`: 音声をそのまま復唱
- `example_apps/echo_with_move.py`: 復唱 + サーボ動作
- `example_apps/gemini.py`: Gemini 応答を発話

## 起動時の目安

1. VOICEVOX を起動
2. FastAPI サーバーを `example_apps.*:app.fastapi` で起動
3. CoreS3 が WebSocket 接続
4. ウェイクワードまたは REST API の wakeword 呼び出しで対話開始
5. 必要に応じて発話・サーボ制御を返送
