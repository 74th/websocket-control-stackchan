# Claude Agent SDKによるAIエージェントアプリケーション開発

[example_apps/claude_agent_sdk/app.py](../example_apps/claude_agent_sdk/app.py) をベースに改変を行い、Claude Agent SDKを利用したエージェントを作る手順を解説します。

> [!CAUTION]
> Claude Agent SDKでは、エージェントがファイルシステムの変更権限を持ちます。
> エージェントに与える指示によっては、意図しないファイルの編集や削除などが行われる可能性があります。
> エージェントに与える指示には十分注意したり、コンテナ環境に置くなどしてください。

## ディレクトリを決める

まず、コードのディレクトリと、ワークスペースとなるディレクトリを決めてください。

コードのディレクトリは、エージェントのプログラムを置くディレクトリです。
ワークスペースとは、Claude Agent SDKの作業ディレクトリです。
ワークスペースにある .claude/ の配下に、スキルやMCPの設定などを置きます。
ワークスペースは、Claude Codeで言うところの、起動ディレクトリに相当します。

## プログラムを作る

コードのディレクトリにて、uvでプロジェクトを初期化します。

```
uv init
```

本リポジトリをライブラリとして追加します。

```
uv add https://github.com/74th/websocket-control-stackchan.git
```

Claude Agent SDKのライブラリも追加します。

```
uv add claude-agent-sdk
```

[example_apps/claude_agent_sdk/app.py](../example_apps/claude_agent_sdk/app.py) を、コードのディレクトリ内にコピーします。

app.py を書き換えていきます。

WORKSPACE_DIR という変数の定義があるため、ワークスペースのディレクトリを設定するように書き換えます。

```py
WORKSPACE_DIR = "/path/to/your_workspace"
```

## サーバの設定の.envファイルの準備

[./server_ja.md](./server_ja.md) で作成した .env ファイルを、コードのディレクトリにコピーしてください。

## サーバを起動する

app.py と言うファイル名で作成した場合、以下のコマンドでサーバを起動します。
ポート番号等は適宜変更してください。

```
uv run uvicorn app:app.fastapi --host 0.0.0.0 --port 8000
```

> [!INFORMATION]
> uvicorn.run()の第一引数は、`{Pythonモジュール名}:{モジュール内のFastAPIアプリケーションの変数名}` という形式になっています。
>
> app.py というファイルを作った場合、Pythonモジュール名も app になります。
> claude_agent_sdk など、既存モジュールと名前が被らないようにしてください。
>
> app.py 内で、app = StackChanApp() というコードがあるため、モジュール内のFastAPIアプリケーションの変数名は app になります。
> app.fastapi がFastAPIのアプリケーションオブジェクトになります。
>
> そのため、uvicorn.run()の第一引数は、`{ファイル名（拡張子なし）}:app.fastapi` という形式になります。

ｽﾀｯｸﾁｬﾝを起動して、「Disconnected」から「Idle」のステータス表示になれば接続されています。
「ハイ！スタックチャン！」と話しかけて、聞くポーズになることを確認して、話しかけてみてください。

## さらに作り込む

以下のClaude Agent SDKのドキュメントを参照して、スキルやMCPの追加など、さらにエージェントを作り込んでみてください。

> https://platform.claude.com/docs/ja/agent-sdk/python
