# REST API 仕様

このドキュメントは、`stackchan_server/app.py` が公開している HTTP API の現行仕様をまとめたものです。

## 概要

- ベース URL 例: `http://localhost:8000`
- 実装: FastAPI
- StackChan の識別子: WebSocket 接続元 IP アドレス (`websocket.client.host`)
- 一覧や取得対象になるのは、現在接続中の StackChan のみです

## エンドポイント一覧

| Method | Path | 説明 |
| --- | --- | --- |
| `GET` | `/health` | ヘルスチェック |
| `GET` | `/v1/stackchan` | 接続中 StackChan 一覧 |
| `GET` | `/v1/stackchan/{stackchan_ip}` | 指定 StackChan の状態取得 |
| `POST` | `/v1/stackchan/{stackchan_ip}/wakeword` | 擬似 wakeword 発火 |
| `POST` | `/v1/stackchan/{stackchan_ip}/speak` | 指定 StackChan に発話させる |

## `GET /health`

サーバーの簡易ヘルスチェックです。

### レスポンス

- Status: `200 OK`

```json
{
  "status": "ok"
}
```

## `GET /v1/stackchan`

現在接続中の StackChan 一覧を返します。

### レスポンス

- Status: `200 OK`

```json
[
  {
    "ip": "192.168.1.23",
    "state": "idle"
  }
]
```

### フィールド

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `ip` | `string` | WebSocket 接続元 IP |
| `state` | `string` | 現在状態 |

### `state` の値

現行実装では以下が返りえます。

- `idle`
- `listening`
- `thinking`
- `speaking`
- `disconnected`

> [!NOTE]
> 一覧 API では `closed` な接続は除外されるため、通常 `disconnected` が長く残り続けることはありません。

## `GET /v1/stackchan/{stackchan_ip}`

指定した StackChan の現在状態を返します。

### パスパラメータ

| 名前 | 型 | 説明 |
| --- | --- | --- |
| `stackchan_ip` | `string` | 対象 StackChan の接続元 IP |

### 成功レスポンス

- Status: `200 OK`

```json
{
  "ip": "192.168.1.23",
  "state": "idle"
}
```

### エラーレスポンス

- Status: `404 Not Found`

```json
{
  "detail": "stackchan not connected"
}
```

## `POST /v1/stackchan/{stackchan_ip}/wakeword`

サーバー内部で wakeword イベントを擬似発火し、`talk_session` の開始待ちを解除します。

### パスパラメータ

| 名前 | 型 | 説明 |
| --- | --- | --- |
| `stackchan_ip` | `string` | 対象 StackChan の接続元 IP |

### リクエストボディ

なし。

### 成功レスポンス

- Status: `204 No Content`

### エラーレスポンス

- Status: `404 Not Found`

```json
{
  "detail": "stackchan not connected"
}
```

### 備考

- 実機側のウェイクワード検出 (`WakeWordEvt`) と同じように扱われます。
- すでに `talk_session` 実行中でも、イベント自体は内部フラグとして立ちます。

## `POST /v1/stackchan/{stackchan_ip}/speak`

指定した StackChan にテキストを発話させます。

### パスパラメータ

| 名前 | 型 | 説明 |
| --- | --- | --- |
| `stackchan_ip` | `string` | 対象 StackChan の接続元 IP |

### リクエストボディ

```json
{
  "text": "こんにちは"
}
```

| フィールド | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| `text` | `string` | 必須 | 発話させるテキスト |

### 成功レスポンス

- Status: `204 No Content`

### エラーレスポンス

- Status: `404 Not Found`

```json
{
  "detail": "stackchan not connected"
}
```

### 備考

- サーバーは TTS 音声を WebSocket で送信し、CoreS3 からの `SpeakDoneEvt` を待ってからレスポンスを返します。
- そのため、この API は「キューに積むだけ」ではなく、発話完了まで待つ同期的な呼び出しです。
- TTS や WebSocket 処理で例外が起きると、FastAPI の既定エラーハンドリングにより `5xx` になる場合があります。

## 補足

### 接続管理

- 同一 IP から再接続が来た場合、古い `WsProxy` は閉じられ、新しい接続で置き換えられます。
- REST API は接続中の `WsProxy` を参照して処理します。

### OpenAPI

- FastAPI の標準 UI が有効なら `/docs` と `/openapi.json` も利用できます。
- 本ドキュメントは実装の要約であり、最終的なレスポンス形状は FastAPI の自動生成スキーマも参照してください。
