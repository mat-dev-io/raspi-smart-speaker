"""設定の読み込み。リポジトリ直下の .env を環境変数に入れる（既にある値は上書きしない）"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"NG: {name} が未設定（.env を確認）")
    return value
