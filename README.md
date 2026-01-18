# StackChan WebSocket Control Server

WebSocketでStackChanを制御するためのサーバーアプリケーションと、そのファームウェアです。

StackChanをフロントにし、メインのロジック処理をPC上のPythonで実現することで、Pythonライブラリを使った外部サービスとの連携などが実装しやすくなることを狙っています。

![Architecture](./docs/architecture.drawio.svg)

> [!CAUTION]
> This is work in progress. The API and functionality may change without notice.

> [!CAUTION]
> これはスタックチャンを楽しむための個人のコミュニティプロジェクトです。M5Stack社や、その他のスタックチャン関連プロダクトとは関係ありません。

## サンプルコード

サンプルアプリケーション [app/](./app/)

以下の簡単な関数で、音声の受信と発話が可能です。

```py
# 音声の受信
text = await proxy.get_message_async()

# 発話
await proxy.start_talking(resp.text)
```

### Geminiの応答

[app/gemini.py](./app/gemini.py)

```py
@app.loop
async def loop(proxy: WsProxy):
    global chat

    # 音声の受信
    text = await proxy.get_message_async()
    logger.info("Human: %s", text)

    # AI応答の取得(Geminiの例)
    resp = await asyncio.to_thread(chat.send_message, text)

    # 発話
    logger.info("AI: %s", resp.text)
    if resp.text:
        await proxy.start_talking(resp.text)
    else:
        await proxy.start_talking("すみません、うまく答えられませんでした。")
```


## 現在開発中の環境

- 本体: M5Stack CoreS3 SE
- 音声認識: Google Cloud Speech-to-Text
- 音声合成: VOICEVOX No.7

## コードの構成

- ファームウェア [firmware/](./firmware/)
- Pythonサーバのライブラリ [stackchan_server/](./stackchan_server/)
- サンプルアプリケーション [app/](./app/)

## 必要なもの

- Google Cloudのプロジェクトとサービスアカウント
- Dockerエンジン
- Python 3.13 以上
  - [uv](https://docs.astral.sh/uv/)
- PlatformIO

## セットアップ

> [!WARNING]
> あくまで最低限のことしか書いていません。各自で環境構築を行ってください。

WiFi設定、接続先サーバを[firmware/include/config.h](firmware/include/config.h)に記述します。

```h
#define WIFI_SSID_H "__SSID__"
#define WIFI_PASSWORD_H "__PASSWORD__"

// WebSocket サーバ設定
#define SERVER_HOST_H "192.168.1.179"   // 例: サーバのIP
#define SERVER_PORT_H 8000              // 例: FastAPIのポート
#define SERVER_PATH_H "/ws/stackchan"      // WebSocketパス
```

StackChanのファームウェアをPlatformIOでビルドして、CoreS3に書き込みます。

PC上で、Google Cloudのログインをしてください。

```bash
gcloud auth application-default login
```

VOICEVOXをdockerで起動します。

```bash
docker compose run --rm --service-ports voicevox
```

Pythonサーバを起動します。

```bash
uv sync
uv run uvicorn app.gemini:app.fastapi --host 0.0.0.0 --port 8000
```
