# AGENTS 概要

本リポジトリにおける ESP32（M5Stack CoreS3）側ファーム `src/main.cpp` とサーバー側 FastAPI 実装 `server/main.py` の役割・プロトコルをまとめる。

## 全体像
- 音声経路: CoreS3 マイク → WebSocket で PCM16LE ストリーミング → サーバー受信 → WAV 保存。
- 制御: CoreS3 の BtnA 長押しで録音・送信開始、離すと終了。0.5 秒ごとに PCM チャンクを送る。
- プロトコル: 独自ヘッダ（`"PCM1"`）+ メッセージ種別（START/DATA/END）+ シーケンス + PCM 長。

## WebSocket プロトコル（PCM1）
- ヘッダ構造 `<4s BB H I H H`（リトルエンディアン）
  - kind: 4 bytes 固定文字列 `"PCM1"`
  - messageType: 1=START, 2=DATA, 3=END
  - reserved: 1 byte（0）
  - seq: uint16（送信側でインクリメント）
  - sampleRate: uint32（例: 16000）
  - channels: uint16（1）
  - payloadBytes: uint16（後続 PCM バイト数）
- ペイロード: PCM16LE モノラル。START/END は通常 0 バイト（payloadBytes=0）。DATA は `payloadBytes` 分の PCM。

## CoreS3 側（`src/main.cpp`）
- Wi-Fi 設定: `config.h` の定義を使用して AP 接続。
- 状態管理: `STATE_IDLE` / `STATE_STREAMING`。
- バッファ: リングバッファ 2 秒分 (`RING_CAPACITY_SAMPLES = SAMPLE_RATE * 2`)。マイクは 256 サンプル単位で読み取り。
- 送信間隔: 0.5 秒相当（`CHUNK_SAMPLES = SAMPLE_RATE / 2` = 8000 サンプル）で DATA を送信。残データは終了時にまとめて送信。
- ボタン操作:
  - BtnA 押下: START パケット送出→状態を STREAMING に遷移。
  - BtnA 離し: 残り PCM を DATA で送信後、END を送信し IDLE に戻す。
- 送信失敗時: WebSocket 未接続や送信失敗で早期リセットし IDLE に戻る。
- ヘルス表示: 画面に接続状態やエラーを簡易表示。

## サーバー側（`server/main.py`）
- フレームワーク: FastAPI。
- 受信エンドポイント:
  - `GET /health`: ヘルスチェック。
  - `POST /api/v1/audio`: HTTP 経由で PCM16LE または μ-law を受信し WAV 保存（従来互換）。
  - `WS /ws/audio`: 上記 PCM1 プロトコルを受信。START→DATA 蓄積→END で WAV を保存し JSON でメタ情報を返信。
- WAV 保存: `server/recordings/rec_ws_YYYYmmdd_HHMMSS_micro.wav` として PCM16LE を保存（サンプル幅 16bit、モノラル）。
- VOICEVOX 連携: END 処理後に VOICEVOX クライアント（`voicevox-client` の `VVClient`）を起動し、`"こんにちは！"` を speaker=1 で合成。生成した WAV を WebSocket BIN メッセージ（`WAV1` + `<uint32 length>` + wav バイト列）で CoreS3 に返送し、CoreS3 側スピーカーで再生する。
  - 期待するサービス: `http://localhost:50021`（docker-compose で `voicevox_engine` がリッスン）。

## 依存・周辺
- VOICEVOX エンジン: `server/docker-compose.yml` に `voicevox/voicevox_engine:cpu-latest` を定義（ホスト 50021 公開）。
- Python パッケージ: `voicevox-client`（`vvclient`）を利用。
- 録音保存先: `server/recordings/`（自動生成）。

## 期待する動作フロー
1. サーバーを起動し VOICEVOX コンテナを立ち上げる（`docker compose up -d` in `server/`）。
2. CoreS3 を Wi-Fi に接続し、BtnA 押下で START 送信→マイク録音開始。
3. 0.5 秒ごとに DATA を連続送信。
4. BtnA を離すと残りを送信して END。サーバー側で WAV 保存→JSON 返信→VOICEVOX 合成 WAV を下り BIN で返し、CoreS3 が再生。
