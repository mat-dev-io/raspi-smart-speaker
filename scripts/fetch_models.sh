#!/usr/bin/env bash
# ローカル STT のモデルを models/ に落とす（Pi で、リポジトリ直下で実行する）
# 使い方: ./scripts/fetch_models.sh   （済んでいるものは飛ばす）
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p models

# ReazonSpeech（k2 zipformer、オフライン transducer）。sherpa-onnx で使う
REAZON=sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01
if [ ! -d "models/$REAZON" ]; then
  # Pi の OS には bzip2 が無いので Python で展開する
  curl -fsSL "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$REAZON.tar.bz2" \
    | .venv/bin/python -c "import sys, tarfile; tarfile.open(fileobj=sys.stdin.buffer, mode='r|bz2').extractall('models', filter='data')"
fi

# faster-whisper（CTranslate2 形式）。Hugging Face から取る
for repo in Systran/faster-whisper-small kotoba-tech/kotoba-whisper-v2.0-faster; do
  dir="models/${repo#*/}"
  [ -d "$dir" ] || .venv/bin/python -c "import sys; from huggingface_hub import snapshot_download as d; d(sys.argv[1], local_dir=sys.argv[2])" "$repo" "$dir"
done
du -sh models/*
