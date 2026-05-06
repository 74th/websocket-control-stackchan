# ファームウェアの設定とビルド

ファームウェアに書き込む設定は firmware/include/config.h に記述します。
[firmware/include/config.template.h](../firmware/include/config.template.h)をコピーして、firmware/include/config.h を作成してください。

## 筐体の選択

ビルドの設定が構成毎に組まれています。

スタータスバー中の"env:m5stack-xxxx"もしくは"env:Default"と書かれている部分をクリックして、選択します。

- env:m5stack-cores3-m5unified: M5Stack CoreS3(SKU:K128, K128-Lite, K128-SE)
- env:m5stack-atoms3r-m5unified: M5Atom S3R(SKU:C126)とAtomic Echo Base(SKU:A149)
- env:m5stack-official-stackchan: M5Stack公式StackChan(SKU:K151)
<!-- - env:m5stack-atoms3r-m5unified: M5Atom EchoS3R(SKU:C126-ECHO) -->

## WiFi設定

WiFi設定、接続先サーバをそれぞれ記述します。

```h
// Wifi
#define WIFI_SSID_H "__SSID__"
#define WIFI_PASSWORD_H "__PASSWORD__"
```

## 接続先サーバ

サーバを立てるIPアドレスを設定してください。
今利用しているPCをサーバにする場合、PCのIPアドレスを設定してください。

なお、PCのIPアドレスが固定されていない場合、IPアドレスが変わると接続できなくなります。
ルータの設定などでIPアドレスを固定することをおすすめします。

FastAPIのポートはデフォルト値を8000にしています。
必要に応じて変更してください。
WebSocketのパスは変更不要です。

```h
// WebSocket Server
#define SERVER_HOST_H "192.168.1.179"   // 例: サーバのIP
#define SERVER_PORT_H 8000              // 例: FastAPIのポート
#define SERVER_PATH_H "/ws/stackchan"      // WebSocketパス
```
## サーボ

サーボモータに合わせて、コメントアウトされている設定の有効化と、ピンの設定を記述してください。
ボディがない構成では、`USE_SERVO_SG90` と `USE_SERVO_SCS0009` のどちらも有効化しないでください。
その場合、ファームウェアはサーボの初期化を行わず、`ServoCmd` を受信しても動作はせずに完了扱いで受け付けます。

### M5Stack公式StackChanの場合

env:m5stack-official-stackchan を選択した場合、SCS0009が有効になります。

SCS0009が使用されており、中心座標がずれている場合があります。
以下を標準値としていますが、必要に応じてオフセット値を調整してください。

```h
#define SCS0009_X_CENTER_OFFSET 0
#define SCS0009_Y_CENTER_OFFSET -35
```

### SG90の場合

以下の設定と、ピンを設定してください。

```h
// -- using SG90 --
#define USE_SERVO_SG90 1

// Pin definitions
#define SERVO_SG90_X_PIN 18
#define SERVO_SG90_Y_PIN 17
```

M5Pantilt、CoreS3のPortA、PortCの設定例があります。

M5Pantiltの場合

```h
#define SERVO_SG90_X_PIN 7
#define SERVO_SG90_Y_PIN 6
```

CoreS3のPortAの場合

```h
#define SERVO_SG90_X_PIN 1
#define SERVO_SG90_Y_PIN 2
```
CoreS3のPortCの場合

```h
#define SERVO_SG90_X_PIN 18
#define SERVO_SG90_Y_PIN 17
```

このファームウェアでは90度を中心に動作します。
90度に位置がずれる場合、オフセット値を設定してください。

```h
#define SERVO_SG90_X_CENTER_OFFSET 0
#define SERVO_SG90_Y_CENTER_OFFSET 0
```

### SCS0009の場合

以下の設定と、ピン、サーボIDを設定してください。

```h
#define USE_SERVO_SCS0009 1

// Pin definitions
#define SCS0009_RX_PIN 17
#define SCS0009_TX_PIN 18

// Servo ID
#define SCS0009_X_ID 1
#define SCS0009_Y_ID 2
```

このファームウェアでは、511を中心に動作します。
511に位置がずれる場合、オフセット値を設定してください。

```h
#define SCS0009_X_CENTER_OFFSET 0
#define SCS0009_Y_CENTER_OFFSET 0
```

### SCS0009のサーボIDの設定

サーボは出荷時はID:1が設定されており、複数のサーボを同時に動かすにはIDの変更が必要です。

以下のファームウェアのコードには、ID:1 のサーボを ID:2 にセットするコードが含まれています。

https://github.com/74th/stackchan-book-code/blob/main/3.4_scs0009

ID:2 にしたいサーボだけを接続してください。
`setID(1, 2);`がコメントアウトされていますので、コメントアウトを外してビルドして、CoreS3に書き込んでください。
実行すると、ID:1 のサーボが ID:2 に変更されます。

## (オプション) RGB LED

ステータスバーの色に合わせてRGB LEDを光らせることができます。

- M5Stack公式StackChanでは、本体のRGB LED 12個が同じ色で光ります。
- それ以外の構成では、`USE_RGBLED` を有効にすると外付けのNeoPixel互換RGB LEDを同じ色で光らせられます。

`RGBLED_BRIGHTNESS` で明るさを調整できます。
値は大きいほど明るくなります。

M5GO Bottom3を使う場合の設定例は以下です。

```h
#define USE_RGBLED 1
#define RGBLED_PIN 5
#define RGBLED_NUM_LEDS 10
#define RGBLED_BRIGHTNESS 255
```

必要に応じて、接続しているLEDの本数とデータピン番号を変更してください。


## ビルドする

StackChanのファームウェアをPlatformIOでビルドして、CoreS3に書き込みます。
