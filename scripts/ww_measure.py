#!/usr/bin/env python3
"""ウェイクワードの見逃しと誤検知を実機で測る（段階 3 の手順 5。Pi で実行する）

使い方（Pi 上、リポジトリ直下で）:
  .venv/bin/python scripts/ww_measure.py miss --distance 1     # Enter → ピッ → 「R2D2」を 1 回。--n 回くり返す
  nohup .venv/bin/python scripts/ww_measure.py fa --hours 10 > logs/ww_fa.out 2>&1 &   # 流しっぱなしで反応を数える
  .venv/bin/python scripts/ww_measure.py summary               # ログをまとめる
miss はピッのあと --window 秒以内に検知したら当たり。fa はウェイクワードを含まない音（会話・テレビ・生活音）を流しておく。
どちらも検知ごとに 1 行 logs/wakeword.jsonl に追記する（録音は残さない）。fa は 10 分ごとに CPU 使用率と温度も残す。
しきい値・確認役は assistant/wakeword.py と同じ（.env の WAKEWORD_*）。
"""
import argparse
import json
import resource
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant import audio  # noqa: E402
from assistant.config import ROOT, load_env  # noqa: E402
from assistant.wakeword import CHUNK, MODEL, Listener, beep  # noqa: E402

LOG = ROOT / "logs" / "wakeword.jsonl"
REFRACTORY = 2.0  # 反応してからこの秒数は数えない（同じ呼びかけで何度も数えない）


def write(rec: dict) -> None:
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def arecord() -> subprocess.Popen:
    return subprocess.Popen(["arecord", "-D", audio.DEVICE, "-q", "-t", "raw", "-f", "S16_LE",
                             "-r", str(audio.RATE), "-c", str(audio.CHANNELS)], stdout=subprocess.PIPE)


def temperature() -> float:
    out = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True).stdout  # temp=52.1'C
    return float(out.split("=")[1].split("'")[0])


def miss(listener: Listener, args) -> None:
    hits = 0
    for i in range(args.n):
        input(f"[{i + 1}/{args.n}] Enter > ")
        player = audio.Player()
        player.write(beep())
        player.close()
        proc = arecord()
        best, hit, t0 = 0.0, False, time.monotonic()
        try:
            listener.model.reset()
            for pcm in listener.chunks(proc):
                score = float(listener.model.predict(pcm)[MODEL.stem])
                best = max(best, score)
                if score >= listener.threshold:
                    hit = True
                    break
                if time.monotonic() - t0 >= args.window:
                    break
        finally:
            proc.terminate()
            proc.wait()
        hits += hit
        write({"ts": datetime.now().isoformat(timespec="seconds"), "kind": "miss", "distance": args.distance,
               "note": args.note, "hit": hit, "score": round(best, 3), "threshold": listener.threshold,
               "verifier": listener.verifier})
        print(f"  {'当たり' if hit else '外れ'}（スコアの最大 {best:.2f}）  ここまで {hits}/{i + 1}")
    print(f"見逃し {args.n - hits}/{args.n}（{(args.n - hits) / args.n:.0%}）")


def fa(listener: Listener, args) -> None:
    end = time.monotonic() + args.hours * 3600
    proc = arecord()
    count, last, next_stat = 0, -1e9, 0.0
    cpu0, t0 = resource.getrusage(resource.RUSAGE_SELF).ru_utime, time.monotonic()
    start = datetime.now().isoformat(timespec="seconds")
    write({"ts": start, "kind": "fa_start", "hours": args.hours, "note": args.note,
           "threshold": listener.threshold, "verifier": listener.verifier})
    n = 0
    try:
        listener.model.reset()
        for n, pcm in enumerate(listener.chunks(proc)):
            now = time.monotonic()
            score = float(listener.model.predict(pcm)[MODEL.stem])
            if score >= listener.threshold and now - last >= REFRACTORY:
                count += 1
                last = now
                write({"ts": datetime.now().isoformat(timespec="seconds"), "kind": "fa", "score": round(score, 3),
                       "start": start})
                print(f"{datetime.now():%H:%M:%S} 反応 {count} 回目（スコア {score:.2f}）", flush=True)
            if now >= next_stat:
                cpu = resource.getrusage(resource.RUSAGE_SELF).ru_utime
                write({"ts": datetime.now().isoformat(timespec="seconds"), "kind": "stat", "start": start,
                       "hours": round(n * CHUNK / audio.RATE / 3600, 3), "count": count,
                       "cpu_pct": round((cpu - cpu0) / max(now - t0, 1e-9) * 100, 1), "temp": temperature()})
                cpu0, t0, next_stat = cpu, now, now + 600
            if now >= end:
                break
    except KeyboardInterrupt:
        print("途中で止めた")
    finally:
        proc.terminate()
        proc.wait()
    hours = n * CHUNK / audio.RATE / 3600  # 途中で止めても、実際に聞いた時間で割る
    write({"ts": datetime.now().isoformat(timespec="seconds"), "kind": "fa_end", "start": start, "count": count,
           "hours": round(hours, 3)})
    print(f"誤検知 {count} 回 / {hours:.2f} 時間" + (f"（{count / hours:.2f} 回/時間）" if hours else ""))


def summary(_listener, _args) -> None:
    recs = [json.loads(line) for line in LOG.open()] if LOG.exists() else []
    by = {}
    for r in recs:
        if r["kind"] == "miss":
            key = (r["distance"], r["threshold"], r["verifier"])
            hit, n = by.get(key, (0, 0))
            by[key] = (hit + r["hit"], n + 1)
    for (d, t, v), (hit, n) in sorted(by.items()):
        print(f"見逃し 距離 {d} m・しきい値 {t}・確認役 {'あり' if v else 'なし'}: {n - hit}/{n}（{(n - hit) / n:.0%}）")
    for s in [r for r in recs if r["kind"] == "fa_start"]:
        stats = [r for r in recs if r["kind"] == "stat" and r["start"] == s["ts"]]
        count = sum(r["kind"] == "fa" and r["start"] == s["ts"] for r in recs)
        end = [r for r in recs if r["kind"] == "fa_end" and r["start"] == s["ts"]]
        hours = end[0]["hours"] if end else (stats[-1]["hours"] if stats else 0)  # 走っている途中なら最後の記録まで
        cpu = [r["cpu_pct"] for r in stats[1:]]  # 最初の 1 行は読み込みを含む
        temp = [r["temp"] for r in stats]
        print(f"誤検知 {s['ts']}〜（{s['note'] or '-'}、しきい値 {s['threshold']}）: {count} 回 / {hours:.1f} 時間"
              + (f"（{count / hours:.2f} 回/時間）" if hours else "")
              + (f"、CPU {min(cpu):.0f}〜{max(cpu):.0f}%" if cpu else "")
              + (f"、温度 {min(temp):.0f}〜{max(temp):.0f} °C" if temp else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["miss", "fa", "summary"])
    ap.add_argument("--n", type=int, default=25, help="miss: 呼びかける回数")
    ap.add_argument("--distance", type=float, default=1.0, help="miss: マイクからの距離（m）")
    ap.add_argument("--window", type=float, default=4.0, help="miss: ピッのあと何秒以内なら当たりか")
    ap.add_argument("--hours", type=float, default=10.0, help="fa: 測る時間")
    ap.add_argument("--note", default="", help="条件のメモ（テレビ、会話 など）")
    args = ap.parse_args()

    load_env()
    listener = None if args.mode == "summary" else Listener()
    {"miss": miss, "fa": fa, "summary": summary}[args.mode](listener, args)


if __name__ == "__main__":
    main()
