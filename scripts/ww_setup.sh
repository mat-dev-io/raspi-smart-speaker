#!/usr/bin/env bash
# ウェイクワードの学習データ作りと学習（段階 3）の環境を WSL に作る（リポジトリ直下で実行する）
# 使い方: ./scripts/ww_setup.sh   （済んでいるものは飛ばす）
# venv は Pi 用の .venv と分けて .venv-ww に作る。VOICEVOX は models/voicevox に入れる（Pi と同じ置き場所）
set -euo pipefail
cd "$(dirname "$0")/.."

VV=0.17.0
[ -d .venv-ww ] || python3 -m venv .venv-ww
.venv-ww/bin/pip -q install \
  "https://github.com/VOICEVOX/voicevox_core/releases/download/$VV/voicevox_core-$VV-cp310-abi3-manylinux_2_34_x86_64.whl" \
  numpy==2.2.6 scipy==1.16.2
# 学習（openWakeWord の train.py）が使うもの。openWakeWord の指定は古く Python 3.12 に入らないので、新しい版を入れて
# scripts/ww_train.py の中で手当てする
.venv-ww/bin/pip -q install torch==2.14.1 torchaudio==2.11.0 torchinfo==1.8.0 torchmetrics==1.9.0 \
  speechbrain==1.1.2 audiomentations==0.43.1 torch-audiomentations==0.12.0 acoustics==0.2.6 mutagen==1.48.1 \
  pronouncing==0.3.0 PyYAML==6.0.3 tqdm==4.70.1 soundfile==0.14.0 onnx==1.23.2 onnxruntime==1.31.0 \
  requests==2.34.2 huggingface_hub==2.3.0 pyarrow==26.0.0 onnxscript==0.7.2

# openWakeWord（学習スクリプトを使う）。v0.6.0 より新しい main のコミットに固定する
OWW=cache/wakeword/openWakeWord
if [ ! -d $OWW ]; then
  git clone -q https://github.com/dscripka/openWakeWord.git $OWW
  git -C $OWW checkout -q 368c037
fi

# VOICEVOX core のランタイム・辞書・トーク用の音声モデル（全部）。ダウンローダーが利用規約を表示するので、読んで y で同意する
if [ ! -d models/voicevox/models ]; then
  mkdir -p models/voicevox
  curl -fsSL -o models/voicevox/download "https://github.com/VOICEVOX/voicevox_core/releases/download/$VV/download-linux-x64"
  chmod +x models/voicevox/download
  models/voicevox/download --only onnxruntime dict models --onnxruntime-version 1.23.2 \
    --models-version "$VV" --models-pattern '[0-9]*.vvm' -o models/voicevox
fi
du -sh models/voicevox/*
