#!/usr/bin/env python3
"""性能のゲート（構成変更 C3）。Pi に配置してベンチを流し、基準（bench/baseline.json）と比べて合否を出す

使い方（WSL、リポジトリ直下で）:
  python3 scripts/perf_gate.py                       # 配置 → ベンチ → 判定。劣化した指標があれば 1 回だけ流し直す
  python3 scripts/perf_gate.py --update-baseline 3   # 今のコードで 3 回流し、基準としきい値を作り直す
  python3 scripts/perf_gate.py --check-only          # 対象のファイルが前回合格から変わっていれば流す（フック用）
終了コード: 0 = 合格（または変更なし）/ 1 = 劣化 / 2 = 環境エラー（Pi に届かない・測れない）
判定のしかたと、しきい値の決め方は docs/c3-perf-gate.md。
"""
import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "bench" / "baseline.json"
PASSED = ROOT / "cache" / "perf_gate" / "passed"  # 合格したときの対象ファイルのハッシュ（コミットしない）
TARGETS = ["assistant", "requirements.txt", "systemd"]  # 性能に関わるファイル。変わったらベンチを流す
HOST = os.environ.get("RASPI_HOST", "raspi")
REMOTE = ("cd raspi-smart-speaker && systemctl --user stop assistant; "
          ".venv/bin/python scripts/perf_bench.py; rc=$?; systemctl --user start assistant; exit $rc")

# 判定に使う指標。表示だけのもの（p90・区間ごと）は SHOW
# 合計や API の待ちは時間帯で数百 ms 揺れ、0.5 秒の劣化を見逃したので判定に使わない（docs/c3-perf-gate.md）
GATED = [("local_ms_median", "手元の処理の中央値", "ms"), ("input_tokens_median", "入力トークン数の中央値", ""),
         ("stt_ms_median", "STT の中央値", "ms"), ("cer", "STT の CER", ""), ("skill_pass", "スキルの合格数", "")]
SHOW = [("total_ms_median", "合計の中央値"), ("total_ms_p90", "合計の p90"), ("api_ms_median", "API の待ちの中央値"),
        ("tts_ms_median", "TTS の中央値")]


def targets_hash() -> str:
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", *TARGETS],
                           capture_output=True, text=True, cwd=ROOT, check=True).stdout.split()
    h = hashlib.sha256()
    for f in sorted(files):
        if (ROOT / f).is_file():
            h.update(f.encode() + b"\0" + (ROOT / f).read_bytes())
    return h.hexdigest()


def run_bench() -> dict | None:
    """配置してベンチを 1 回流す。測れなければ None"""
    if subprocess.run([str(ROOT / "scripts" / "deploy.sh")], cwd=ROOT).returncode != 0:
        print("NG: 配置できない（deploy.sh）")
        return None
    proc = subprocess.run(["ssh", HOST, REMOTE], capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT "):])
    print(f"NG: ベンチが測れなかった（終了コード {proc.returncode}）\n{proc.stdout[-800:]}{proc.stderr[-800:]}")
    return None


def limits(base: dict) -> dict:
    """しきい値。決め方は docs/c3-perf-gate.md"""
    v, spread = base["value"], base["spread"]
    return {"local_ms_median": v["local_ms_median"] + max(100, spread["local_ms_median"]),
            "input_tokens_median": round(v["input_tokens_median"] * 1.2),
            "stt_ms_median": round(v["stt_ms_median"] * 1.2),
            "cer": round(v["cer"] + 0.02, 4),
            "skill_pass": v["skill_total"]}  # これ未満なら劣化（ほかは超えたら劣化）


def judge(result: dict, lim: dict) -> list[str]:
    bad = []
    for key, label, _ in GATED:
        if key == "skill_pass":
            if result[key] < lim[key]:
                bad.append(key)
        elif result[key] > lim[key]:
            bad.append(key)
    return bad


def table(results: list[dict], base: dict, lim: dict) -> str:
    head = "| 指標 | 基準 | しきい値 | " + " | ".join(f"{i + 1} 回目" for i in range(len(results))) + " |"
    lines = [head, "|---|---:|---:|" + "---:|" * len(results)]
    for key, label, _ in GATED:
        cells = []
        for r in results:
            mark = " ✗" if key in judge(r, lim) else ""
            cells.append(f"{r[key]}{mark}")
        op = "≥" if key == "skill_pass" else "≤"
        lines.append(f"| {label} | {base['value'][key]} | {op} {lim[key]} | " + " | ".join(cells) + " |")
    for key, label in SHOW:
        lines.append(f"| {label}（表示のみ） | {base['value'][key]} | - | " + " | ".join(str(r[key]) for r in results) + " |")
    return "\n".join(lines)


def update_baseline(n: int) -> int:
    runs = []
    for i in range(n):
        print(f"== 基準の測定 {i + 1}/{n}", flush=True)
        r = run_bench()
        if r is None:
            return 2
        runs.append(r)
        print(json.dumps(r, ensure_ascii=False))
    keys = [k for k, *_ in GATED] + [k for k, _ in SHOW] + ["skill_total"]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    base = {"created": datetime.now().isoformat(timespec="seconds"), "commit": commit,
            "config": {k: runs[0][k] for k in ("model", "effort", "stt_model", "voice", "skills")},
            "value": {k: round(statistics.median(r[k] for r in runs), 4) for k in keys},
            "spread": {k: round(max(r[k] for r in runs) - min(r[k] for r in runs), 4) for k in keys},
            "runs": runs}
    base["limits"] = limits(base)
    BASELINE.parent.mkdir(exist_ok=True)
    BASELINE.write_text(json.dumps(base, ensure_ascii=False, indent=1) + "\n")
    print(f"\n基準を書いた: {BASELINE.relative_to(ROOT)}\n")
    print(table(runs, base, base["limits"]))
    mark_passed()
    return 0


def mark_passed() -> None:
    PASSED.parent.mkdir(parents=True, exist_ok=True)
    PASSED.write_text(targets_hash())


def gate() -> int:
    base = json.loads(BASELINE.read_text())
    lim = limits(base)
    results = []
    for attempt in range(2):  # 劣化した指標があれば 1 回だけ流し直す（Claude の遅延のばらつき対策）
        r = run_bench()
        if r is None:
            return 2
        results.append(r)
        if not judge(r, lim):
            break
    # 流し直したときは、2 回とも悪かった指標だけを劣化とする
    bad = set(judge(results[0], lim))
    for r in results[1:]:
        bad &= set(judge(r, lim))
    print("\n" + table(results, base, lim))
    cfg = {k: results[-1][k] for k in base["config"]}
    if cfg != base["config"]:
        print(f"\n注意: 設定が基準と違う（基準 {base['config']} / 今 {cfg}）。意図した変更なら --update-baseline で作り直す")
    if bad:
        labels = [label for key, label, _ in GATED if key in bad]
        print(f"\nNG: 性能が劣化した（{', '.join(labels)}）。作業を止めて人に知らせる")
        return 1
    print("\nOK: 基準から劣化していない")
    mark_passed()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update-baseline", type=int, metavar="N", help="N 回流して基準を作り直す")
    parser.add_argument("--check-only", action="store_true", help="対象のファイルが前回合格から変わっていなければ何もしない")
    args = parser.parse_args()
    if args.update_baseline:
        return update_baseline(args.update_baseline)
    if not BASELINE.exists():
        print(f"NG: 基準がない（{BASELINE.relative_to(ROOT)}）。--update-baseline 3 で作る")
        return 2
    if args.check_only and PASSED.exists() and PASSED.read_text() == targets_hash():
        print("OK: 性能に関わるファイルは前回合格から変わっていない（ベンチは流さない）")
        return 0
    return gate()


if __name__ == "__main__":
    sys.exit(main())
