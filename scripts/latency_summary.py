#!/usr/bin/env python3
"""logs/latency.jsonl の区間ごとの遅延を集計して Markdown の表で出す

使い方: python3 scripts/latency_summary.py [--source wav:] [--since 2026-10-18T12:00] [--skip-first N]
"""
import argparse
import json
import statistics
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "logs" / "latency.jsonl"
COLUMNS = [("stt_ms", "STT"), ("llm_ms", "Claude"), ("tts_ms", "TTS"),
           ("play_ms", "再生開始"), ("total_ms", "合計")]
# 段階 2 から（1 文ずつ合成する作り）。古い行には無いので、全行にあるときだけ出す
EXTRA = [("tts_all_ms", "全文の合成"), ("stall_ms", "途中の無音")]


def p90(values: list[int]) -> float:
    return statistics.quantiles(values, n=10, method="inclusive")[-1] if len(values) > 1 else values[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default=str(LOG))
    parser.add_argument("--source", default="", help="source がこの文字列で始まる行だけ（例: wav: / mic）")
    parser.add_argument("--since", default="", help="ts がこの時刻以降の行だけ（ISO 形式）")
    parser.add_argument("--skip-first", type=int, default=0, help="先頭 N 件を除く（接続の暖機分）")
    args = parser.parse_args()

    rows = [json.loads(line) for line in Path(args.log).read_text().splitlines() if line.strip()]
    rows = [r for r in rows if "total_ms" in r and r["source"].startswith(args.source) and r["ts"] >= args.since]
    rows = rows[args.skip_first:]
    if not rows:
        raise SystemExit("該当する記録がない")

    print(f"n={len(rows)}  model={sorted({r['model'] for r in rows})}  voice={sorted({r['voice'] for r in rows})}"
          f"  stt={sorted({r['stt_model'] for r in rows})}\n")
    print("| 区間 | 中央値 | p90 | 最小 | 最大 |")
    print("|---|---:|---:|---:|---:|")
    for key, label in COLUMNS + [c for c in EXTRA if all(c[0] in r for r in rows)]:
        v = [r[key] for r in rows]
        print(f"| {label} | {statistics.median(v):.0f} | {p90(v):.0f} | {min(v)} | {max(v)} |")
    print("\n（単位 ms。起点は録音終了＝Enter を押した時刻、終点は再生開始）")


if __name__ == "__main__":
    main()
