# Claude Agent SDKをDockerコンテナ上で実行する

以下の手順は、[create_your_claude_agent_sdk_apps.md](./create_your_claude_agent_sdk_apps.md) を行った後の手順となります。

本手順では、docker composeを利用して、Claude Agent SDKをDockerコンテナ上で実行する方法を解説します。

## 必要ファイルをコピーする

[example_apps/claude_agent_sdk](../example_apps/claude_agent_sdk) にある以下のファイルを、コードのディレクトリにコピーします。

- [.dockerignore](../example_apps/claude_agent_sdk/.dockerignore)
- [Dockerfile](../example_apps/claude_agent_sdk/Dockerfile)
- [docker-compose.yml](../example_apps/claude_agent_sdk/docker-compose.yml)

## app.py のワークスペースのパスを修正する

app.py 内のワークスペースのパスは、コンテナ内のパスに書き換える必要があります。

コンテナ内のパスは `/app/workspace` となります。そのように、app.py 内の WORKSPACE_DIR の定義を書き換えてください。

```py
WORKSPACE_DIR = "/app/workspace"
```

## docker-compose ファイルの編集

### Google Cloudのサービスアカウントの秘密鍵のJSONファイルをマウントする

Google Cloudのサービスアカウントの秘密鍵のJSONファイルを、コンテナ内にマウントして、コンテナ内から参照可能にする必要があります。

以下にサービスアカウントの秘密鍵のJSONファイルがある例として、説明します。

> /Users/foobar/google_cloud_credentials/application_credentials.json

volumesの項目にある/path/to/your/google_cloud_credentials の部分を、置かれているディレクトリに書き換えてください。

```yaml
    volumes:
      # Google Cloud service account key JSON directory
      - /Users/foobar/google_cloud_credentials:/secrets/google_cloud_credentials:ro
```

すると、そのディレクトリが /secrets/google_cloud_credentials としてコンテナ内にマウントされます。

environmentの項目にあるGOOGLE_APPLICATION_CREDENTIALSの値を、マウントしたディレクトリ内のJSONファイルのパスに書き換えてください。

```yaml
    environment:
      GOOGLE_APPLICATION_CREDENTIALS: /secrets/google_cloud_credentials/application_credentials.json
```

### ワークスペースのディレクトリをマウントする

ワークスペースのディレクトリをコンテナ内にマウントする必要があります。

以下にワークスペースのディレクトリがある例として、説明します。

> /Users/foobar/stackchan_workspace

volumesの項目にある ./workspace の部分を、置かれているディレクトリに書き換えてください。

```yaml
    volumes:
      # Workspace directory
      - /Users/foobar/stackchan_workspace:/app/workspace
```

### VOICEVOXを使わない場合

VOICEVOXのコンテナを起動するようになっています。
VOICEVOXを使わない場合、services.voicevoxの記述を削除、もしくはコメントアウトしてください。

```yaml
services:
  app:
    ...
# voicevox:
#   image: voicevox/voicevox_engine:cpu-latest
#   ports:
#     - "50021:50021"
```

また、services.app.depends_on の項目も削除、もしくはコメントアウトしてください。

```yaml
services:
  app:
    ...
# depends_on:
#   - voicevox
```

## コンテナのビルド

このコンテナをビルドするには、コードのディレクトリにて、以下のコマンドを実行してください。

```
docker compose build
```

## コンテナの起動、終了、削除

このコンテナを起動するには、コードのディレクトリにて、以下のコマンドを実行してください。

```
docker compose up -d
```

起動を確認するには、以下のコマンドを実行します。

```
docker compose ps -a
```

STATUSが「Up」になっていれば、起動しています。
「Exited」になっている場合は、コンテナが終了しています。

コンテナのログを確認するには、以下のコマンドを実行してください。

```
docker compose logs app
```

コンテナを一度起動した場合、異常終了したとしてもコンテナインスタンスは残り続けます。
設定やコンテナのビルドをやり直して、再度起動したい場合には、一度削除した上で起動する必要があります。

コンテナを停止するには以下のコマンドを実行します。

```
docker compose stop
```

コンテナを削除するには以下のコマンドを実行します。

```
docker compose rm -f
```

この後に、コンテナのビルドからやり直してください。
