#!/bin/bash
set -xe

whisper-server \
  --host 0.0.0.0 \
  --port ${STACKCHAN_WHISPER_SERVER_PORT} \
  -m ${STACKCHAN_WHISPER_SERVER_MODEL_PATH} \
  -l ja \
  -nt \
  --vad \
  -vm ${STACKCHAN_WHISPER_SERVER_VAD_MODEL_PATH} \
  -vt 0.6 \
  -vspd 250 \
  -vsd 400 \
  -vp 30
