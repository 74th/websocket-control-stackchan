# セットアップ方法

このプロダクトを動かすには、以下の準備が必要です。

1. ｽﾀｯｸﾁｬﾝのハードウェアを用意する
2. ｽﾀｯｸﾁｬﾝのMCUとなるESP32-S3に、ファームウェアを書き込む
3. WebSocket サーバーをPC上で動かす

## 必要なもの

Claude Agent SDKを利用したエージェントを動かす場合、以下のものが必要になります。

1. ｽﾀｯｸﾁｬﾝのハードウェア
2. Google Cloudの契約
    - 有償ですが、従量制料金で無料枠もあります
    - 音声認識にGoogle Cloud Speech-to-Textを利用
    - Claude Agent SDKの利用にもGoogle Cloud Vertex AIを利用
3. PC
    - Windows / macOS / Linux いずれも可
    - 以下の役割を担います
        - ファームウェアのビルド
        - WebSocket サーバー

## ｽﾀｯｸﾁｬﾝのハードウェア

ｽﾀｯｸﾁｬﾝのハードウェアには以下が必要です。

- M5Stackコアシリーズ
- 外装ケース
- ケース対応コアシリーズと接続するための接続ボード
- サーボ

このプロダクトでは M5Stack CoreS3 が必要です。
M5Stack Basic、M5Stack Core2は対応していません。

### 対応M5Stack

以下の製品に対応しています。

- M5Stack CoreS3 SE
    - [スイッチサイエンス](https://www.switch-science.com/products/9690)
- M5Stack CoreS3 Lite
    - [スイッチサイエンス](https://www.switch-science.com/products/10610)
- M5Stack CoreS3
    - [スイッチサイエンス](https://www.switch-science.com/products/8960)
- M5Stack ATOMS3R AI Chatbotキット（M5Stack Atom S3R と Atomic Echo Baseのセット）
    - [スイッチサイエンス](https://www.switch-science.com/products/10487)
<!--
- M5Stack Atom VoiceS3R
    - [スイッチサイエンス](https://www.switch-science.com/products/10808)
-->

> [!CAUTION]
> ESP-SR の利用には、PSRAM付きESP32-S3が必要になります。そのため、M5Stack Basic/Core2 は利用できません。

### 対応サーボ

- Tower Pro SG90
    - [秋月電子通商](https://akizukidenshi.com/catalog/g/g108761/)
- FEETECH SCS0009
    - [秋月電子通商](https://akizukidenshi.com/catalog/g/g131664/)
    - [スイッチサイエンス](https://www.switch-science.com/products/8042)

なお、サーボがなくても動作します。

### 対応確認済み外装ケースと接続ボード

- 原典のししかわさん製作ケースと、その接続ボードの組み合わせ
    - [公開ケースデータ](https://github.com/stack-chan/stack-chan/blob/dev/v1.0/case/README_ja.md)
    - [接続ボード m5-pantilt](https://github.com/stack-chan/stack-chan/tree/dev/v1.0/schematics)
- Takaoさん製作ケースと、その接続ボードの組み合わせ
    - [公開ケースデータ stackchan_sg90_case_takao_version](https://github.com/mongonta0716/3DPrinter_Models/tree/master/stackchan_sg90_case_takao_version) ([@mongonta555](https://x.com/mongonta555))
        - [TakaoさんのBoothショップ](https://mongonta.booth.pm/)でケースが販売されています
    - [接続ボード Stack-Chan_Takao_Base](https://github.com/akita11/Stack-chan_Takao_Base) ([@akita11](https://x.com/akita11))
        - スイッチサイエンスで[部品セット](https://www.switch-science.com/products/8906)、[完成品](https://www.switch-science.com/products/8905)が販売されています

なお、ボディがない、M5Stack CoreS3単体でも動作します。

## Google Cloudの契約と設定方法

[./google_cloud_ja.md](./google_cloud_ja.md) を参照してください。

## ファームウェアビルド環境の構築

ファームウェアのビルドには、PlatformIOを利用します。

[./platformio_ja.md](./platformio_ja.md) を参照して、環境を構築してください。

## ファームウェアの設定とビルド

以下のページを参照して、ファームウェアの設定とビルドを行ってください。

[./firmware_ja.md](./firmware_ja.md)

## （オプション）VOICEVOXのDockerコンテナの実行

標準ではGoogle Cloud Text-to-Speechを利用して音声合成を行います。
無料で利用できる中品質の音声合成エンジンのVOICEVOXも利用できます。
キャラクターボイスが多くてかわいいので、VOICEVOXもぜひ試してみてください。

VOICEVOXを利用する際には、VOICEVOXの利用規約の参照をお願いします。

https://voicevox.hiroshiba.jp/

VOICEVOXはDockerイメージが提供されているため、Docker環境を構築して実行します。

Dockerがインストールされていない場合は以下のページを参照して、Dockerをインストールしてください。

> 今すぐ始める | Docker
>
> https://www.docker.com/ja-jp/get-started/

Dockerがインストールできたら、リポジトリのディレクトリで以下の起動コマンドを実行してください。

```
# 起動
docker compose -f ./misc/voicevox/docker-compose.yml up -d

# 起動の確認（STATUSがUpになっていればOK）
docker compose -f ./misc/voicevox/docker-compose.yml ps -a

# 停止（インスタンスが残るため、削除が必要です）
docker compose -f ./misc/voicevox/docker-compose.yml stop

# 削除
docker compose -f ./misc/voicevox/docker-compose.yml rm
```

以下のサイトにアクセスし、「VOICEVOX Engine」と表示されていれば成功です。

> http://localhost:50021/

## （オプション）Whisper.cppのwhisper-cliのインストール

標準ではGoogle Cloud Speech-to-Textを利用して音声認識を行います。
無料で利用できるWhisper.cppのwhisper-cliも利用できます。

(TODO)

## （オプション）Whisper.cppのwhisper-serverのインストールと実行

標準ではGoogle Cloud Speech-to-Textを利用して音声認識を行います。
無料で利用できるWhisper.cppのwhisper-serverも利用できます。

(TODO)

## Python開発環境の構築

このリポジトリでは、WebSocket サーバーをPythonで実装しています。
Pythonの環境構築の方法は、パッケージマネージャuvのページを参照してください。

> Installation | uv
>
> https://docs.astral.sh/uv/getting-started/installation/

## サーバの設定

以下のページを参照して、サーバの設定を行ってください。

[server_ja.md](./server_ja.md)

## サンプルアプリケーションの実行

まずは、サンプルアプリケーションを実行してみましょう。

以下のページを参照して、サンプルアプリケーションの実行方法を確認してください。

[run_sample_app_ja.md](./run_sample_app_ja.md)

## Claude Agent SDKによるAIエージェントアプリケーションの開発

Claude Agent SDKを利用したAIエージェントアプリケーションの開発方法は、以下のページを参照してください。

[create_your_claude_agent_sdk_apps.md](./create_your_claude_agent_sdk_apps.md)

## Claude Agent SDKをDockerコンテナ上で実行する

Dockerコンテナを使うと、ファイルシステムが隔離されるため、Claude Agent SDKを安全に実行できます。
以下のページを参照してください。

[create_docker_container_ja.md](./create_docker_container_ja.md)
