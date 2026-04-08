# サンプルアプリケーションの実行

複数のサンプルアプリケーションが実装されています。

- [example_apps/echo_with_move.py](../example_apps/echo_with_move.py): 音声認識した内容をそのまま音声合成して返す。ボディも動かして聞くポーズをします。
- [example_apps/gemini.py](../example_apps/gemini.py): Gemini応答
- [example_apps/claude_agent_sdk/app.py](../example_apps/claude_agent_sdk/app.py): Claude Agent SDKを利用したエージェント

## おうむ返しサンプル

uv で必要なライブラリをインストールします。

```
uv sync
```

その後、以下のコマンドでPythonサーバを起動します。

```
uv run uvicorn example_apps.echo_with_move:app.fastapi --host 0.0.0.0 --port 8000
```

スタックチャンを起動して、「Disconnected」から「Idle」のステータス表示になれば接続されています。

試しに「ハイ！スタックチャン！」と話しかけて、聞くポーズになることを確認して、話しかけてみてください。

## Gemini応答サンプル

uv で必要なライブラリをインストールします。
追加でgeminiのクライアントが必要です。

```
uv sync --group example-gemini
```

その後、以下のコマンドでPythonサーバを起動します。

```
uv run uvicorn example_apps.gemini:app.fastapi --host 0.0.0.0 --port 8000
```

スタックチャンを起動して、「Disconnected」から「Idle」のステータス表示になれば接続されています。

試しに「ハイ！スタックチャン！」と話しかけて、聞くポーズになることを確認して、話しかけてみてください。

## Claude Agent SDKサンプル

Claude Agent SDKのエージェントはファイルシステムの変更権限を持ちます。
意図しないファイル編集をするような指示を与えないように注意してください。

TODO: サンプルアプリはファイル編集、読取権限を剥奪する

### NodeJSのインストール

NodeJSのインストールも必要です。
以下からインストールを進めてください。

> https://nodejs.org/ja/download

### Pythonライブラリのインストール

uv で必要なライブラリをインストールします。
追加でclaude agent sdkのクライアントが必要です。

```
uv sync --group example-claude-agent-sdk
```

### Claude Agent SDKの環境変数設定

Claude Agent SDKを利用するには、VertexAIを利用する場合、以下の.envもしくは環境変数の設定が必要です。

#### VertexAIを利用する場合

- `CLAUDE_CODE_USE_VERTEX`: `1`
- `CLOUD_ML_REGION`: リージョン設定 "global"
- `ANTHROPIC_VERTEX_PROJECT_ID`: Google CloudのプロジェクトID（`GCLOUD_PROJECT`と同じ値）
- `GOOGLE_APPLICATION_CREDENTIALS`: Google Cloudのサービスアカウントの秘密鍵のJSONファイルのパス

#### Claude APIを利用する場合

- `ANTHROPIC_API_KEY`: Claude APIのAPIキー

### サーバの起動

その後、以下のコマンドでPythonサーバを起動します。

```
uv run uvicorn example_apps.claude_agent_sdk.app:app.fastapi --host 0.0.0.0 --port 8000
```

スタックチャンを起動して、「Disconnected」から「Idle」のステータス表示になれば接続されています。

試しに「ハイ！スタックチャン！」と話しかけて、聞くポーズになることを確認して、話しかけてみてください。
