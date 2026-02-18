# AGENTS 概要

本リポジトリの現行実装（`firmware/` と `stackchan_server/`）の役割と、WebSocket バイナリプロトコルをまとめる。

## 全体像
- 音声経路（上り）: CoreS3 マイク → `AudioPcm` で PCM16LE ストリーミング → サーバー受信 → WAV 保存 → Google Cloud Speech-to-Text。
- 音声経路（下り）: サーバー側で VOICEVOX 合成 → `AudioWav` で PCM 分割送信 → CoreS3 スピーカー再生。
- 制御: CoreS3 は `StateMachine` で `Idle` / `Listening` / `Speaking` を遷移。
- トリガ: `Idle` 中に WakeWord 検出で `Listening` に遷移。`Listening` は無音 3 秒で自動終了。

## WebSocket プロトコル（現行）
- 共通ヘッダ: `WsHeader`（`firmware/include/protocols.hpp`）
- 構造（packed, little-endian）: `<B B B H H`
  - `kind` (`uint8`): 1=`AudioPcm`, 2=`AudioWav`
  - `messageType` (`uint8`): 1=`START`, 2=`DATA`, 3=`END`
  - `reserved` (`uint8`): 0
  - `seq` (`uint16`): 送信側でインクリメント
  - `payloadBytes` (`uint16`): ヘッダ直後のバイト数

### Uplink（CoreS3 -> Server, kind=1 AudioPcm）
- 形式: PCM16LE / 16kHz / 1ch 固定。
- シーケンス: `START`（payload なし）→ `DATA` 複数回 → `END`（payload なし）。
- `Listening` は 0.5 秒相当（8000 samples）ごとに `DATA` 送信。終了時に残りバッファを flush。

### Downlink（Server -> CoreS3, kind=2 AudioWav）
- 実体は WAV コンテナではなく「PCM 本体のストリーム分割」。
- 1セグメントの流れ:
  - `START`: payload `<uint32 sample_rate><uint16 channels>`
  - `DATA`: raw PCM chunk（既定 4096 bytes）
  - `END`: payload なし
- サーバーは合成 PCM を約 2 秒単位でセグメント化し、2 本目を 1 秒後に先行開始して連続再生しやすくしている。

## CoreS3 側（`firmware/`）
- エントリポイント: `firmware/src/main.cpp`
  - Wi-Fi 接続後、`/ws/stackchan` に接続。
  - WS 受信で `kind=AudioWav` を `Speaking` に渡す。
- `WakeUpWord`（`firmware/src/wake_up_word.cpp`）
  - `Idle` 中に `ESP_SR_M5` へマイク音声を feed。
  - WakeWord 検出で `Listening` へ遷移。
- `Listening`（`firmware/src/listening.cpp`）
  - 2 秒リングバッファ、マイク読み取り 256 サンプル単位。
  - `START/DATA/END` を送信。
  - 無音閾値（平均絶対値 200 以下）が 3 秒続くと自動停止して `Idle` へ戻る。
  - 送信失敗時も `Idle` へフォールバック。
- `Speaking`（`firmware/src/speaking.cpp`）
  - `AudioWav` の `START` でメタ情報取得、`DATA` 蓄積、`END` で `M5.Speaker.playRaw` 再生。
  - 再生完了後 `Idle` に戻る。
- `Display`（`firmware/src/display.cpp`）
  - 状態色のみ表示: `Idle=黒`, `Listening=青`, `Speaking=緑`。

## サーバー側（`stackchan_server/`）
- FastAPI 本体: `stackchan_server/app.py`
  - `GET /health`
  - `WS /ws/stackchan`
- WS 処理: `stackchan_server/ws_proxy.py`
  - 受信 `AudioPcm` を蓄積し、`END` 時に `stackchan_server/recordings/rec_ws_*.wav` として保存。
  - その PCM を Google Cloud Speech-to-Text（`ja-JP`, LINEAR16, 16kHz）で文字起こし。
  - `get_message_async()` でアプリ層へ認識結果を渡す。
  - `start_talking(text)` で VOICEVOX（`http://localhost:50021`, speaker=29）合成し、`AudioWav` として分割送信。

## アプリ層（`app/`）
- `app/echo.py`: 認識結果をそのまま VOICEVOX で復唱。
- `app/gemini.py`: 認識結果を Gemini チャットに渡し、応答文を VOICEVOX で発話。

## 依存・周辺
- VOICEVOX エンジン: ルート `docker-compose.yml` の `voicevox` サービス（`50021:50021`）。
- Python 依存: `fastapi`, `uvicorn`, `voicevox-client`, `google-cloud-speech`, `google-genai`。
- 録音保存先: `stackchan_server/recordings/`（自動生成）。

## 期待する動作フロー
1. VOICEVOX を起動（ルートで `docker compose run --rm --service-ports voicevox` など）。
2. サーバーを起動（例: `uv run uvicorn app.gemini:app.fastapi --host 0.0.0.0 --port 8000`）。
3. CoreS3 が Wi-Fi/WS 接続後、`Idle` で WakeWord 待機。
4. WakeWord 検出で録音送信開始。無音 3 秒で送信終了。
5. サーバーが WAV 保存・文字起こしし、アプリ層の応答文を VOICEVOX 合成。
6. 合成 PCM が `AudioWav` で返送され、CoreS3 が再生して `Idle` に戻る。
