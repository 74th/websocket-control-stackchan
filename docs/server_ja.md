# サーバの設定

## .envファイルの作成

サーバの基本設定は`.env`ファイル、もしくは環境変数に全て記述します。
リポジトリのルートディレクトリに、`.env`という名前のファイルを作成してください。

次から、`.env`ファイルに記述する環境変数を説明します。

## Google Cloudの設定

[./google_cloud_ja.md](./google_cloud_ja.md) にて、Google Cloudのプロジェクトを作成し、サービスアカウントの秘密鍵のJSONファイルダウンロードしました。

この値を記述します。

- `GCLOUD_PROJECT`: プロジェクト名
- `GOOGLE_APPLICATION_CREDENTIALS`: ダウンロードしたサービスアカウントの秘密鍵のJSONファイルのパス

プロジェクト名は、秘密鍵のJSONファイル中に記載されている、`project_id`の値と同じものを指定してください。

```
GCLOUD_PROJECT="your-gcloud-project-id"
GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```

この設定は、Google Cloud Speech-to-Text(STT)、Google Cloud Text-to-Speech(TTS)の両方で使用されます。

## 音声認識の設定

音声認識エンジンとして、以下に対応しています。

- Google Cloud Speech-to-Text
- Whisper.cppのwhisper-server
- Whisper.cppのwhisper-cli

### Google Cloud Speech-to-Textの設定

以下の値を設定します。

- `STACKCHAN_USE_GOOGLE_CLOUD_STT`: `1`
- `STACKCHAN_GOOGLE_CLOUD_STT_LANGUAGE_CODE`: BCP-47 言語コード

BCP-47 言語コードは以下のページを参照してください。

https://docs.cloud.google.com/speech-to-text/docs/speech-to-text-supported-languages

```
STACKCHAN_USE_GOOGLE_CLOUD_STT=1
STACKCHAN_GOOGLE_CLOUD_STT_LANGUAGE_CODE="ja-JP"
```

### Whisper.cppのwhisper-cliの設定

(WIP)

```
STACKCHAN_USE_WHISPER_CLI=1
STACKCHAN_WHISPER_CLI_MODEL_PATH="/path/to/whisper.cpp/ggml-small.bin"
STACKCHAN_WHISPER_CLI_VAD_MODEL_PATH="/path/to/whisper.cpp/ggml-silero-v5.1.2.bin"
```

### Whisper.cppのwhisper-serverの設定

(WIP)

```
STACKCHAN_USE_USE_WHISPER_SERVER=1
STACKCHAN_WHISPER_SERVER_PORT=8431
```

## 音声合成の設定

音声合成エンジンとして、以下に対応しています。

- Google Cloud Text-to-Speech
- VOICEVOX

### Google Cloud Text-to-Speechの設定

以下の値を設定します。

- `STACKCHAN_USE_GOOGLE_CLOUD_TTS`: `1`
- `STACKCHAN_GOOGLE_CLOUD_TTS_MODEL`: モデル
- `STACKCHAN_GOOGLE_CLOUD_TTS_LANGUAGE_CODE`: BCP-47 言語コード
- `STACKCHAN_GOOGLE_CLOUD_TTS_VOICE_NAME`: 音声の名前

モデルは以下から選択できます。

https://docs.cloud.google.com/text-to-speech/docs/gemini-tts#available_models

対応言語は以下から確認してください。

https://docs.cloud.google.com/text-to-speech/docs/gemini-tts#available_languages

ボイス名は以下から確認してください。（サンプル音声は英語ですが、日本語に対応しているようです）

https://docs.cloud.google.com/text-to-speech/docs/gemini-tts#voice_options

```
STACKCHAN_USE_GOOGLE_CLOUD_TTS=1
STACKCHAN_GOOGLE_CLOUD_TTS_MODEL="gemini-2.5-flash-tts"
STACKCHAN_GOOGLE_CLOUD_TTS_LANGUAGE_CODE="ja-JP"
STACKCHAN_GOOGLE_CLOUD_TTS_VOICE_NAME="Despina"
```

### VOICEVOXの設定

VOICEVOXを利用する際には、VOICEVOXの利用規約の参照をお願いします。

https://voicevox.hiroshiba.jp/

[./setup_ja.md](./setup_ja.md) の手順で立ち上げた場合、http://localhost:50021/ でVOICEVOXのAPIが利用できるようになっています。

以下の値を設定します。

- `STACKCHAN_USE_VOICEVOX`: `1`
- `STACKCHAN_VOICEVOX_URL`: VOICEVOXのAPIのURL
- `STACKCHAN_VOICEVOX_SPEAKER`: 使用するキャラクターのスピーカーID

キャラクターの一覧は下記のページにあります。
キャラクターによって利用規約が異なります。

https://voicevox.hiroshiba.jp/#characters

キャラクターからスピーカーIDの確認が必要です。

VOICEVOXが立ち上がっている場合、/speakers にアクセスすると、スピーカーIDとキャラクターの対応表がJSON形式で表示されます。
キャラクター毎の構造があり、その中にキャラクターのstyleがあります。
styleの id がスピーカーIDになります。

> http://localhost:50021/speakers

```
STACKCHAN_USE_VOICEVOX=1
STACKCHAN_VOICEVOX_URL="http://localhost:50021"
STACKCHAN_VOICEVOX_SPEAKER=1
```
