#!/bin/bash
set -xe

/opt/whisper.cpp/build/bin/whisper-server \
    --host 0.0.0.0 \
    --port "8431" \
    --model /opt/whisper.cpp/models/ggml-small.bin \
    -l ja \
    -nt \
    -sns \
    -vt "0.5" \
    -vspd "100" \
    -vsd "500" \
    -vp "200" \
    --convert
