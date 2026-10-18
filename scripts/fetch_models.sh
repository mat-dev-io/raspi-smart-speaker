#!/usr/bin/env bash
# ローカル STT・TTS のモデルを models/ に落とす（Pi で、リポジトリ直下で実行する）
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
# VOICEVOX core のランタイム・辞書・音声モデル（0.vvm だけ）。ダウンローダーが利用規約を表示するので、読んで y で同意する
VV=0.17.0
if [ ! -d models/voicevox/models ]; then
  mkdir -p models/voicevox
  curl -fsSL -o models/voicevox/download "https://github.com/VOICEVOX/voicevox_core/releases/download/$VV/download-linux-arm64"
  chmod +x models/voicevox/download
  models/voicevox/download --only onnxruntime dict models --onnxruntime-version 1.23.2 \
    --models-version "$VV" --models-pattern 0.vvm -o models/voicevox
fi

# Open JTalk の男声 takumi（MMDAgent の example に入っている。女声 mei は pyopenjtalk-plus に同梱）
if [ ! -f models/htsvoice/takumi_normal.htsvoice ]; then
  mkdir -p models/htsvoice
  curl -fsSL -o models/htsvoice/mmdagent.zip \
    "https://sourceforge.net/projects/mmdagent/files/MMDAgent_Example/MMDAgent_Example-1.8/MMDAgent_Example-1.8.zip/download"
  .venv/bin/python - <<'PY'
import zipfile
with zipfile.ZipFile("models/htsvoice/mmdagent.zip") as z:
    for name in ["takumi_normal.htsvoice", "COPYRIGHT.txt", "README.txt"]:
        data = z.read(f"MMDAgent_Example-1.8/Voice/takumi/{name}")
        open(f"models/htsvoice/{name.replace('.txt', '-takumi.txt')}", "wb").write(data)
PY
  rm models/htsvoice/mmdagent.zip
fi
du -sh models/*
