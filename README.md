# StackChan WebSocket Control Server

WebSocketでStackChanを制御するためのサーバーアプリケーションと、そのファームウェアです。

StackChanをフロントにし、メインのロジック処理をPC上のPythonで実現することで、Pythonライブラリを使った外部サービスとの連携などが実装しやすくなることを狙っています。

![Architecture](./docs/image/architecture.drawio.svg)

> [!CAUTION]
> This is work in progress. The API and functionality may change without notice.

> [!CAUTION]
> これはｽﾀｯｸﾁｬﾝを楽しむための個人のコミュニティプロジェクトです。M5Stack社や、その他のｽﾀｯｸﾁｬﾝ関連プロダクトとは関係ありません。

## サンプルコード

サンプルアプリケーション [example_apps/](./example_apps/)

以下の関数で、wake word（Hi, StackChan!） を起点に対話セッションを実装できます。
また、画面および、公式スタックチャン頭部のタッチセンサーでも対話セッションを開始できます。

```py
@app.talk_session
async def talk_session(proxy: WsProxy):
    text = await proxy.listen()
    await proxy.speak(text)
```

### Geminiの応答

```
uv sync --group example-gemini
```

[example_apps/gemini.py](./example_apps/gemini.py)

```py
app = StackChanApp()

client = genai.Client(vertexai=True).aio

@app.setup
async def setup(proxy: WsProxy):
    logger.info("WebSocket connected")

@app.talk_session
async def talk_session(proxy: WsProxy):
    chat = client.chats.create(
        model="gemini-3-flash-preview",
        config=types.GenerateContentConfig(
            system_instruction="あなたは親切な音声アシスタントです。音声で返答するため、マークダウンは記述せず、簡潔に答えてください。だいたい3文程度で答えてください。",
        ),
    )

    while True:
        # 聞くポーズ
        await proxy.move_servo([(ServoMoveType.MOVE_Y, 80, 100)])

        try:
            # 音声認識
            text = await proxy.listen()
        except EmptyTranscriptError:
            # 音声なし
            await proxy.move_servo([(ServoMoveType.MOVE_Y, 90, 100)])
            return

        logger.info("Human: %s", text)

        # 頷く
        await proxy.move_servo(
            [
                (ServoMoveType.MOVE_Y, 100, 100),
                (ServoWaitType.SLEEP, 200),
                (ServoMoveType.MOVE_Y, 90, 100),
                (ServoWaitType.SLEEP, 200),
                (ServoMoveType.MOVE_Y, 100, 100),
                (ServoWaitType.SLEEP, 200),
                (ServoMoveType.MOVE_Y, 90, 100),
            ]
        )

        # AI応答の取得
        resp = await chat.send_message(text)

        # 話す
        logger.info("AI: %s", resp.text)
        if resp.text:
            await proxy.speak(resp.text)
```

`StackChanApp()` は既定で、WebSocket 接続直後に WakeWord 検出通知音をデバイスへ送信しようとします。
送信する音は環境変数 `STACKCHAN_WAKEWORD_SOUND_PATH` で指定した WAV ファイルから読み込みます。
読み込んだ WAV は送信前に 16-bit PCM / 24kHz / mono へ正規化されます。
さらに短い通知音でも再生しやすいよう、送信前に前後へ短い無音を付与し、最小再生長を確保します。
この値が未設定なら通知音は送信されません。
送信された音はデバイス側で SPIFFS に保存され、WakeWord 検出時にローカル再生されます。
接続時送信の機能自体を無効化したい場合は `StackChanApp(send_wakeword_sound_on_connect=False)` を使ってください。

## セットアップ

以下を確認ください。

[docs/setup_ja.md](docs/setup_ja.md)


## 現在開発中の環境

- コア:
    - M5Stack CoreS3(SKU:K128, K128-Lite, K128-SE)
    - M5Stack Atom S3R(SKU:C126) + Atomic Echo Base(SKU:A149)
    - M5Stack公式StackChan(SKU:K151)
    - M5Stack Atom EchoS3R
- サーボ（なくても動作します）:
    - Tower Pro SG90
    - FEETECH SCS0009
- 音声認識:
    - Google Cloud Speech-to-Text
    - Whisper.cpp
- 音声合成:
    - Google Cloud Text-to-Speech
    - VOICEVOX

## コードの構成

- ファームウェア [firmware/](./firmware/)
- Pythonサーバのライブラリ [stackchan_server/](./stackchan_server/)
- サンプルアプリケーション [example_apps/](./example_apps/)

## LICENSE

[MIT License](./LICENSE.md)

This project includes files derived from third-party MIT-licensed projects.
See [NOTICE.md](./NOTICE.md) for third-party copyright and license notices.
