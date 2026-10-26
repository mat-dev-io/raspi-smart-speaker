#!/usr/bin/env bash
# 音のループバックテスト（WSL で実行する）。Pi に配置してから assistant.loopback を走らせる
# 使い方: ./scripts/loopback.sh [--inject silence|noise|dropout] [--keep DIR] [--tts google|openjtalk|voicevox]
# 終了コード: 0 = 合格 / 1 = 不合格 / 2 = 環境エラー（Pi 上の終了コードをそのまま返す）
set -euo pipefail

HOST="${RASPI_HOST:-raspi}"
cd "$(dirname "$0")/.."

./scripts/deploy.sh >/dev/null
ARGS=""
[ $# -gt 0 ] && ARGS="$(printf '%q ' "$@")"
# 常駐中のアシスタント（systemd/assistant.service）とはマイクを取り合うので、テストの間だけ止めて、終わったら戻す
ssh "$HOST" "systemctl --user is-active -q assistant && systemctl --user stop assistant && touch /tmp/assistant-paused; \
  cd raspi-smart-speaker && .venv/bin/python -m assistant.loopback $ARGS; code=\$?; \
  [ -f /tmp/assistant-paused ] && rm /tmp/assistant-paused && systemctl --user start assistant; exit \$code"
