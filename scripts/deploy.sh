#!/usr/bin/env bash
# WSL → Pi へコードを配置し、venv の依存を揃える（WSL で実行する）
# 使い方: ./scripts/deploy.sh   （ssh の接続先は RASPI_HOST、既定は raspi）
set -euo pipefail

HOST="${RASPI_HOST:-raspi}"
DEST="raspi-smart-speaker"
cd "$(dirname "$0")/.."

# .env・録音・ログ・TTS のキャッシュ・モデルは Pi 側にだけあるので、除外して消さない
rsync -a --delete \
  --exclude .git/ --exclude .venv/ --exclude .env --exclude logs/ --exclude recordings/ --exclude cache/ --exclude models/ --exclude __pycache__/ \
  ./ "$HOST:$DEST/"

ssh "$HOST" "cd $DEST && { [ -d .venv ] || python3 -m venv .venv; } && .venv/bin/pip install -q -r requirements.txt"
echo "OK: $HOST:~/$DEST に配置した"
