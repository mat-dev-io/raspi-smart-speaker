#!/usr/bin/env python3
"""STT 単体のベンチ。録音済み WAV を STT_ENGINE の STT に通し、遅延と文字誤り率（CER）を出す

使い方（Pi 上、リポジトリ直下で）:
  STT_ENGINE=reazon .venv/bin/python scripts/stt_bench.py --refs recordings/refs.tsv --repeat 3
refs.tsv は「WAV のファイル名<TAB>正解文」。正解の表記が何通りかあるときは | で区切る（最も近いものと比べる）。
WAV は refs.tsv と同じディレクトリから読む。結果は logs/stt_bench.jsonl に 1 行ずつ追記する。
"""
import argparse
import json
import resource
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from assistant import audio  # noqa: E402
from assistant.config import ROOT, load_env  # noqa: E402
from assistant.loopback import normalize  # noqa: E402
from assistant.stt import make_stt  # noqa: E402

LOG = ROOT / "logs" / "stt_bench.jsonl"


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def errors(refs: list[str], hyp: str) -> tuple[int, int]:
    """(誤り文字数, 正解の文字数)。誤りは候補のうち最も近いもので数え、文字数はエンジンによらず最初の候補で数える"""
    h = normalize(hyp)
    return min(edit_distance(normalize(r), h) for r in refs), len(normalize(refs[0]))


def p90(values: list[float]) -> float:
    return statistics.quantiles(values, n=10, method="inclusive")[-1] if len(values) > 1 else values[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refs", required=True)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()

    load_env()
    refs_path = Path(args.refs)
    items = []
    for line in refs_path.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            name, ref = line.split("\t", 1)
            items.append((name, ref.split("|"), audio.read_wav_mono(str(refs_path.parent / name))))

    t0 = time.monotonic()
    stt = make_stt(httpx.Client(timeout=30))
    load_s = time.monotonic() - t0

    latencies, rtfs, err, total, rows = [], [], 0, 0, []
    for i in range(args.repeat):
        for name, refs, pcm in items:
            t = time.monotonic()
            hyp = stt.transcribe(pcm)
            sec = time.monotonic() - t
            e, n = errors(refs, hyp)
            if i == 0:
                rows.append((name, hyp, e, n))
                err, total = err + e, total + n
            # 1 件目はモデルの暖機（クラウドは TLS 接続の確立）を含むので除く
            if (i, name) != (0, items[0][0]):
                latencies.append(sec * 1000)
                rtfs.append(sec / (len(pcm) / 2 / audio.RATE))
            print(f"[{i + 1}/{args.repeat}] {sec * 1000:6.0f} ms  誤り {e}/{n}  {name}  {hyp}")

    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    summary = {"ts": datetime.now().isoformat(timespec="seconds"), "stt_model": stt.model,
               "n": len(latencies), "load_s": round(load_s, 2), "rss_mb": round(rss_mb),
               "median_ms": round(statistics.median(latencies)), "p90_ms": round(p90(latencies)),
               "min_ms": round(min(latencies)), "max_ms": round(max(latencies)),
               "rtf": round(statistics.median(rtfs), 3), "cer": round(err / total, 3),
               "errors": err, "chars": total,
               "results": [{"wav": n, "hyp": h, "errors": e, "chars": c} for n, h, e, c in rows]}
    print(f"\n{stt.model}: 中央値 {summary['median_ms']} ms / p90 {summary['p90_ms']} ms"
          f"  RTF {summary['rtf']}  CER {summary['cer']:.1%}（{err}/{total}）"
          f"  読み込み {summary['load_s']} s  メモリ {summary['rss_mb']} MB")
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
