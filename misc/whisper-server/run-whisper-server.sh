#!/bin/bash
set -xe

whisper-server \
  --host 0.0.0.0 \
  --port ${STACKCHAN_WHISPER_SERVER_PORT} \
  -m ${STACKCHAN_WHISPER_MODEL} \
  -l ja \
  -nt \
  --vad \
  -vm ${STACKCHAN_WHISPER_VAD_MODEL} \
  -vt 0.6 \
  -vspd 250 \
  -vsd 400 \
  -vp 30
