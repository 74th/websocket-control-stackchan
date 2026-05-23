#!/bin/bash

MODEL_NAME="gemma4:26b"
CONTEXT_SIZE=$((1024 * 128))

curl http://localhost:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d "{
    \"model\": \"$MODEL_NAME\",
    \"keep_alive\": -1,
    \"options\": {
      \"num_ctx\": $CONTEXT_SIZE
    }
  }'"
