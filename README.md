# M5Stack CoreS3 SEをフロントに、PC上のPythonで自在に作れる、音声AIエージェントを作るための準備コード

WebSocket経由で、PCに、マイクの音声を送信して、さらに音声データを受け取ってスピーカーで発話できる。

この音声受け取って返すまでの部分をAIエージェント化すれば、様々な応用ができそう。

![](./graph.drawio.svg)

- ファームウェアのコード: [src/main.cpp](./src/main.cpp)
- FastAPIサーバーのコード: [server/main.py](./server/main.py)

## 参考コード

M5Unified Microphone サンプル https://github.com/m5stack/M5Unified/blob/master/examples/Basic/Microphone/Microphone.ino
