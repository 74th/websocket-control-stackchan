# ファームウェアの設定とビルド

TODO 詳細を書く

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
