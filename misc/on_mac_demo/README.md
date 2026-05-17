need Xcode app

```
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
```

```
sudo git clone https://github.com/ggml-org/whisper.cpp /opt/whisper.cpp
sudo chown -R $(id -u):$(id -g) /opt/whisper.cpp

cd /opt/whisper.cpp

uv venv -p 3.11
uv pip install ane_transformers openai-whisper coremltools
source .venv/bin/activate
```

```
./models/generate-coreml-model.sh small
./models/download-ggml-model.sh small
./models/generate-coreml-model.sh large-v3-turbo
./models/download-ggml-model.sh large-v3-turbo
```

```
# rm -rf build
cmake -B build -DWHISPER_COREML=ON -DWHISPER_FFMPEG=ON -DGGML_NATIVE=OFF
cmake --build build -j --config Release
```
