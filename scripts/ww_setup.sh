#!/usr/bin/env bash
# ウェイクワードの学習データ作り（段階 3）の環境を WSL に作る（リポジトリ直下で実行する）
# 使い方: ./scripts/ww_setup.sh   （済んでいるものは飛ばす）
# venv は Pi 用の .venv と分けて .venv-ww に作る。VOICEVOX は models/voicevox に入れる（Pi と同じ置き場所）
set -euo pipefail
cd "$(dirname "$0")/.."

VV=0.17.0
[ -d .venv-ww ] || python3 -m venv .venv-ww
.venv-ww/bin/pip -q install \
  "https://github.com/VOICEVOX/voicevox_core/releases/download/$VV/voicevox_core-$VV-cp310-abi3-manylinux_2_34_x86_64.whl" \
  numpy==2.2.6 scipy==1.16.2

# VOICEVOX core のランタイム・辞書・トーク用の音声モデル（全部）。ダウンローダーが利用規約を表示するので、読んで y で同意する
if [ ! -d models/voicevox/models ]; then
  mkdir -p models/voicevox
  curl -fsSL -o models/voicevox/download "https://github.com/VOICEVOX/voicevox_core/releases/download/$VV/download-linux-x64"
  chmod +x models/voicevox/download
  models/voicevox/download --only onnxruntime dict models --onnxruntime-version 1.23.2 \
    --models-version "$VV" --models-pattern '[0-9]*.vvm' -o models/voicevox
fi
du -sh models/voicevox/*
