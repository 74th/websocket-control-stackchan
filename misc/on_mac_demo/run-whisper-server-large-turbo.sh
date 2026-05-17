#!/bin/bash
set -xe

whisper-server \
    --host 0.0.0.0 \
    --port "8432" \
    --model /opt/whisper.cpp/models/ggml-large-v3-turbo-q8_0.bin \
    -l ja \
    -nt \
    -sns \
    --vad \
    -vm /opt/whisper.cpp/models/ggml-silero-v6.2.0.bin \
    -vt "0.5" \
    -vspd "100" \
    -vsd "500" \
    -vp "200"
