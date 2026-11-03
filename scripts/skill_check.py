#!/usr/bin/env python3
"""スキルの選び方の確認（段階 4）。決めた質問を文字で Claude に聞き、呼ばれたスキルが期待どおりかを表で出す

STT・TTS・マイクは使わない。LIFE への記録は既定で dry-run（実際には書かない）。
使い方（リポジトリ直下で）: .venv/bin/python scripts/skill_check.py [--real-life] [--only 6]
終了コード: 0 = 全問合格 / 1 = 不合格あり / 2 = 環境エラー（API キーがない・API に届かない）
合否: 期待するスキルをすべて呼び、それ以外に呼んだのが get_datetime だけなら合格（日時の確認は害がない）
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic  # noqa: E402

from assistant import skills  # noqa: E402
from assistant.config import load_env  # noqa: E402
from assistant.llm import Claude  # noqa: E402

HARMLESS = {"get_datetime"}
CASES = [
    ("今日は何日？", {"get_datetime"}),
    ("今何時？", {"get_datetime"}),
    ("今日は何曜日？", {"get_datetime"}),
    ("明日の天気は？", {"get_weather"}),
    ("今日は傘を持っていったほうがいい？", {"get_weather"}),
    ("LIFE に牛乳を買うと記録して", {"record_to_life"}),
    ("歯医者の予約を取るのをやることに入れておいて", {"record_to_life"}),
    ("LIFE って何？", set()),
    ("富士山の高さは？", set()),
    ("記録って英語で何て言う？", set()),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--real-life", action="store_true", help="LIFE に本当に記録する（LIFE_DRY_RUN を外す）")
    parser.add_argument("--only", type=int, nargs="+", help="この番号（1 始まり）の質問だけ流す")
    args = parser.parse_args()

    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("NG: ANTHROPIC_API_KEY が未設定（.env を確認）")
        return 2
    if not args.real_life:
        os.environ["LIFE_DRY_RUN"] = "1"
    llm = Claude(skills.load(os.environ.get("SKILLS") or ",".join(skills.AVAILABLE)))

    failed = 0
    rows = []
    for n, (question, expected) in enumerate(CASES, 1):
        if args.only and n not in args.only:
            continue
        t = time.monotonic()
        try:
            reply = llm.ask(question)
        except (anthropic.APIConnectionError, anthropic.AuthenticationError) as e:
            print(f"NG: API に届かない（{type(e).__name__}）")
            return 2
        sec = time.monotonic() - t
        called = set(llm.last["skills"])
        ok = expected <= called and called - expected <= HARMLESS
        failed += not ok
        rows.append((n, "OK" if ok else "NG", question, ",".join(sorted(expected)) or "-",
                     ",".join(llm.last["skills"]) or "-", llm.last["rounds"], f"{sec:.1f}",
                     llm.last["skill_errors"], reply.replace("|", "／")))
        print(f"[{n}] {rows[-1][1]} {question} → {rows[-1][4]}: {reply}", flush=True)

    print("\n| # | 合否 | 質問 | 期待 | 呼んだ | 問い合わせ | 秒 | スキルの失敗 | 答え |")
    print("|---|---|---|---|---|---:|---:|---:|---|")
    for r in rows:
        print("| " + " | ".join(str(x) for x in r) + " |")
    print(f"\n{'OK' if not failed else 'NG'}: {len(rows) - failed}/{len(rows)} 合格"
          f"（model={llm.model} effort={llm.effort}、LIFE は{'本当に記録' if args.real_life else ' dry-run'}）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
