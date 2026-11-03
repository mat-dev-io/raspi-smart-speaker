"""スキル（Claude のツール呼び出しで使う道具）。1 スキル 1 ファイルで、各ファイルは SKILL を持つ

使うスキルは .env の SKILLS にカンマ区切りで書く（例: SKILLS=datetime,weather,life）。空なら使わない（段階 3 と同じ）。
"""
import importlib
import json
import os
from dataclasses import dataclass
from typing import Callable

# SKILLS に書く名前 → モジュール
AVAILABLE = {"datetime": "clock", "weather": "weather", "life": "life"}


@dataclass
class Skill:
    name: str          # Claude に見せるツール名
    description: str   # いつ使うか・何を返すか
    input_schema: dict  # strict にするので additionalProperties: false と required を必ず書く
    run: Callable[[dict], dict]  # 入力を受けて、Claude に返す結果（JSON にできる dict）を返す。失敗は例外で

    def tool(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": self.input_schema, "strict": True}


def load(names: str | None = None) -> list[Skill]:
    names = os.environ.get("SKILLS", "") if names is None else names
    skills = []
    for key in [n.strip() for n in names.split(",") if n.strip()]:
        if key not in AVAILABLE:
            raise SystemExit(f"NG: SKILLS の {key} は無い（使えるのは {', '.join(AVAILABLE)}）")
        skills.append(importlib.import_module(f".{AVAILABLE[key]}", __name__).SKILL)
    return skills


def result_text(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)
