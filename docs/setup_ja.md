# セットアップ方法

このプロダクトを動かすには、以下の準備が必要です。

1. ｽﾀｯｸﾁｬﾝのハードウェアを用意する
2. ｽﾀｯｸﾁｬﾝのMCUとなるESP32-S3に、ファームウェアを書き込む
3. WebソケットサーバをPC上で動かす

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
        - Webソケットサーバ

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

> [!CAUTION]
> ESP-SR の利用に、MCUにPRRAM付きESP32-S3が必要になります。このMCUではなく、M5Stack Basic/Core2は利用できません。

### 対応サーボ

- Tower Pro SG90
    - [秋月電子通商](https://akizukidenshi.com/catalog/g/g108761/)

### 対応確認済み外装ケースと接続ボード

- 原典のししかわさん製作ケースと、その接続ボードの組み合わせ
    - [公開ケースデータ](https://github.com/stack-chan/stack-chan/blob/dev/v1.0/case/README_ja.md)
    - [接続ボード m5-pantilt](https://github.com/stack-chan/stack-chan/tree/dev/v1.0/schematics)
- Takaoさん製作ケースと、その接続ボードの組み合わせ
    - [公開ケースデータ stackchan_sg90_case_takao_version](https://github.com/mongonta0716/3DPrinter_Models/tree/master/stackchan_sg90_case_takao_version) ([@mongonta555](https://x.com/mongonta555))
        - [TakaoさんのBoothショップ](https://mongonta.booth.pm/)でケースが販売されています
    - [接続ボード Stack-Chan_Takao_Base](https://github.com/akita11/Stack-chan_Takao_Base) ([@akita11](https://x.com/akita11))
        - スイッチサイエンスで[部品セット](https://www.switch-science.com/products/8906)、[完成品](https://www.switch-science.com/products/8905)が販売されています

## Google Cloudの契約と設定方法

[./google_cloud_ja.md](./google_cloud_ja.md) を参照してください。

## ファームウェアビルド環境の構築

ファームウェアのビルドには、PlatformIOを利用します。

[./platformio_ja.md](./platformio_ja.md) を参照して、環境を構築してください。

## ファームウェアの設定とビルド

[./firmware_ja.md](./firmware_ja.md) を参照して、ファームウェアの設定とビルドを行ってください。

## Docker環境の構築

標準のサーバ

TODO

## Python開発環境の構築

TODO

## サンプルアプリケーションの実行

TODO

## アプリケーションの設定

TODO

## Claude Agent SDKによるエージェントの構築と実行

TODO

## Docker環境で実行する
