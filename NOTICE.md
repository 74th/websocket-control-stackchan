# Third-Party Notices

This repository includes files derived from third-party licensed software.

## m5stack-platformio-boilerplate-code

- Files:
    - platformio-m5stack.ini
    - platformio.ini
- Project: Boilerplate Code for M5Stack in PlatformIO IDE Environment
- Repository: https://github.com/3110/m5stack-platformio-boilerplate-code
- Original author: SAITO, Tetsuya
- License: MIT License
- Original copyright:

```text
Copyright (c) 2024 SAITO, Tetsuya

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Firmware dependencies

- Standard M5Unified environments:
    - Adafruit NeoPixel - https://github.com/adafruit/Adafruit_NeoPixel - LGPL-3.0-or-later
    - WebSockets - https://github.com/Links2004/arduinoWebSockets.git - LGPL-2.1
    - AsyncTCP - https://github.com/ESP32Async/AsyncTCP.git - LGPL-3.0
    - ESP32Servo - https://madhephaestus.github.io/ESP32Servo/annotated.html - LGPL-2.1-or-later
    - Nanopb - https://github.com/nanopb/nanopb - Zlib
    - ESP_SR_M5Unified - https://github.com/74th/ESP-SR-For-M5Unified.git - LGPL-2.1
    - SCServo - https://github.com/mongonta0716/SCServo.git - MIT
    - M5GFX - https://github.com/m5stack/M5GFX.git - MIT
    - M5Unified - https://github.com/m5stack/M5Unified.git - MIT
- `m5stack-official-stackchan` only:
    - StackChan-BSP - https://github.com/m5stack/StackChan-BSP - MIT
- Framework:
    - framework-arduinoespressif32 - https://github.com/espressif/arduino-esp32 - LGPL-2.1-or-later

## Python server dependencies

- Runtime dependencies:
    - fastapi - https://github.com/fastapi/fastapi - MIT
    - google-genai - https://github.com/googleapis/python-genai - Apache-2.0
    - google-cloud-speech - https://github.com/googleapis/google-cloud-python/tree/main/packages/google-cloud-speech - Apache-2.0
    - uvicorn - https://github.com/Kludex/uvicorn - BSD-3-Clause
    - voicevox-client - https://github.com/voicevox-client/python - MIT
    - python-dotenv - https://github.com/theskumar/python-dotenv - BSD-3-Clause
    - pydantic-settings - https://github.com/pydantic/pydantic-settings - MIT
    - protobuf - https://developers.google.com/protocol-buffers/ - BSD-3-Clause
- Development dependencies:
    - grpcio-tools - https://github.com/grpc/grpc/tree/master/tools/distrib/python/grpcio_tools - Apache-2.0
    - ruff - https://github.com/astral-sh/ruff - MIT
    - ty - https://github.com/astral-sh/ty - MIT
- Example-only dependencies:
    - claude-agent-sdk - https://github.com/anthropics/claude-agent-sdk-python - MIT
