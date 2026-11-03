#!/usr/bin/env python3
"""性能のベンチ（構成変更 C3）。遅延・STT の精度・スキルの選び方を 1 回で測り、JSON で出す

使い方（Pi 上、リポジトリ直下で。アシスタントは止めておく。ふつうは WSL の scripts/perf_gate.py から呼ぶ）:
  .venv/bin/python scripts/perf_bench.py [--repeat 2] [--out logs/perf_bench.json]
測るもの:
  遅延      合計（total_ms）を、API の待ち（api_ms）と手元の処理（local_ms = total_ms − api_ms）に分ける。
            入力トークン数（input_tokens）も出す。段階 1 の録音（recordings/refs.tsv の 9 問）を main.py と同じ Pipeline に --repeat 周通す。
            音は再生しない（total_ms は再生を始めるまでなので値は変わらない。stall_ms は使えない）。
            1 件目は暖機（モデルの読み込み・TLS）を含むので除く
  STT の精度  1 周目の聞き取り結果と refs.tsv の正解の文字誤り率（CER。stt_bench.py と同じ数え方）
  スキル    scripts/skill_check.py の合格数（LIFE は dry-run）
最後の行に「RESULT {json}」を出す。終了コード: 0 = 測れた / 2 = 環境エラー
"""
import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from assistant import audio, main as assistant_main  # noqa: E402
from assistant.config import ROOT, load_env  # noqa: E402
from stt_bench import errors, p90  # noqa: E402

REFS = ROOT / "recordings" / "refs.tsv"


class NullPlayer:
    """audio.Player の代わり。再生せずに捨てる"""

    def write(self, chunk: bytes) -> None:
        pass

    def close(self) -> None:
        pass


def latency_and_cer(repeat: int) -> dict:
    items = []
    for line in REFS.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            name, ref = line.split("\t", 1)
            items.append((name, ref.split("|"), audio.read_wav_mono(str(REFS.parent / name))))

    audio.Player = NullPlayer  # main.py は audio.Player() を呼ぶので、ここで差し替える
    pipe = assistant_main.Pipeline()
    rows, err, chars = [], 0, 0
    for i in range(repeat):
        for name, refs, pcm in items:
            rec = pipe.run(pcm, f"bench:{name}", time.monotonic())
            if i == 0:
                e, n = errors(refs, rec["transcript"] if rec else "")
                err, chars = err + e, chars + n
            if rec:
                rows.append(rec)
    rows = rows[1:]
    out = {"n": len(rows), "cer": round(err / chars, 4), "cer_errors": err, "cer_chars": chars,
           "model": pipe.llm.model, "effort": pipe.llm.effort, "stt_model": pipe.stt.model,
           "voice": pipe.tts.voice, "skills": sorted(pipe.llm.skills)}
    for r in rows:
        r["local_ms"] = r["total_ms"] - r["api_ms"]  # 手元の処理時間（STT・TTS・自分のコード。API の待ちを除く）
    for key in ("total_ms", "local_ms", "api_ms", "input_tokens", "stt_ms", "llm_ms", "tts_ms"):
        values = [r[key] for r in rows]
        out[f"{key}_median"] = round(statistics.median(values))
        out[f"{key}_p90"] = round(p90(values))
    return out


def skill_pass() -> dict:
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "skill_check.py")],
                          capture_output=True, text=True, cwd=ROOT)
    m = re.search(r"(\d+)/(\d+) 合格", proc.stdout)
    if proc.returncode == 2 or not m:
        raise RuntimeError(f"skill_check.py が環境エラー: {proc.stdout[-300:]}{proc.stderr[-300:]}")
    return {"skill_pass": int(m.group(1)), "skill_total": int(m.group(2))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--out", default=str(ROOT / "logs" / "perf_bench.json"))
    args = parser.parse_args()

    load_env()
    if not REFS.exists():
        print(f"NG: {REFS} がない")
        return 2
    try:
        result = {"ts": datetime.now().isoformat(timespec="seconds"), **latency_and_cer(args.repeat), **skill_pass()}
    except Exception as e:  # noqa: BLE001 — 何であれ「測れなかった」として 2 を返す
        print(f"NG: 測れなかった（{type(e).__name__}: {e}）")
        return 2
    Path(args.out).parent.mkdir(exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print("RESULT " + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
