"""LIFE（GitHub の mat-dev-io/LIFE）に Issue として記録する

.env の LIFE_GITHUB_TOKEN に fine-grained PAT（LIFE だけ・Issues の書き込みだけ）を入れる。
LIFE_DRY_RUN=1 なら書かずに、書く予定の内容を返す。ラベルは付けない（本文の一行で見分ける）。
"""
import os
from datetime import datetime

import httpx

from . import Skill

MARK = "音声アシスタント（raspi-smart-speaker）から記録"


def run(args: dict) -> dict:
    repo = os.environ.get("LIFE_REPO", "mat-dev-io/LIFE")
    title = args["title"].strip()
    if not title:
        raise ValueError("title が空")
    body = f"{MARK}（{datetime.now():%Y-%m-%d %H:%M}）"
    if args["note"].strip():
        body += f"\n\n{args['note'].strip()}"
    if os.environ.get("LIFE_DRY_RUN") == "1":
        print(f"  [LIFE dry-run] {repo}: {title} / {body!r}")
        return {"dry_run": True, "title": title}
    token = os.environ.get("LIFE_GITHUB_TOKEN")
    if not token:
        raise RuntimeError("LIFE_GITHUB_TOKEN が未設定")
    r = httpx.post(f"https://api.github.com/repos/{repo}/issues", timeout=10,
                   headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                            "X-GitHub-Api-Version": "2022-11-28"},
                   json={"title": title, "body": body})
    r.raise_for_status()
    return {"recorded": True, "number": r.json()["number"], "title": title}


SKILL = Skill(
    name="record_to_life",
    description="利用者のタスク管理（LIFE）に、やること・メモを 1 件記録する。"
                "利用者が「記録して」「メモして」「やることに入れて」のようにはっきり記録を頼んだときだけ使う。"
                "LIFE についての質問や、記録を頼んでいない話では使わない。",
    input_schema={"type": "object", "properties": {
        "title": {"type": "string", "description": "記録する内容。利用者の言葉をなるべくそのまま、短い 1 行で"},
        "note": {"type": "string", "description": "補足（期限や詳細）。なければ空文字"}},
        "required": ["title", "note"], "additionalProperties": False},
    run=run,
)
