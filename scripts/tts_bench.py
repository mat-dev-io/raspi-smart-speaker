#!/usr/bin/env python3
"""TTS 単体のベンチ。文を TTS_ENGINE の TTS に通し、遅延と、合成音を Google STT で聞き取った文字誤り率（CER）を出す

使い方（Pi 上、リポジトリ直下で）:
  TTS_ENGINE=openjtalk .venv/bin/python scripts/tts_bench.py --texts recordings/tts_texts.txt --repeat 3
texts は 1 行に 1 つの文章（Claude の回答など）。測るのは次の 3 つ:
  全文: 文章をまとめて合成する時間（段階 1 の tts_ms と同じ）
  1 文目: 文に分けたときの 1 文目の合成時間（1 文ずつ再生するときの待ち時間）
  無音: 1 文ずつ合成しながら再生したとき、次の文が間に合わずに空く時間の合計
CER は 1 周目の全文の合成音を Google STT（latest_long）に通し、元の文章と比べて数える。
読みが同じ表記の違い（数字/漢数字 など）を除くため、かなに直して比べた値（かな CER）も出す。
結果は logs/tts_bench.jsonl に 1 行ずつ追記する。--keep DIR で合成音を WAV で残す。
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
from assistant.stt import GoogleSTT  # noqa: E402
from assistant.tts import make_tts, split_sentences  # noqa: E402
from stt_bench import edit_distance, p90  # noqa: E402

LOG = ROOT / "logs" / "tts_bench.jsonl"


def kana(text: str) -> str:
    """読み（カタカナ）。pyopenjtalk の読みの推定に頼るので、目安として使う"""
    import pyopenjtalk

    return normalize(pyopenjtalk.g2p(text, kana=True))


def timed(tts, text: str) -> tuple[float, bytes]:
    t = time.monotonic()
    pcm = audio.wav_pcm(tts.synthesize(text))
    return time.monotonic() - t, pcm


def stall_sec(chunks: list[tuple[float, bytes]]) -> float:
    """1 文ずつ合成しながら再生したとき、次の文の合成が前の文の再生に間に合わなかった時間の合計"""
    ready = play_end = stall = 0.0
    for i, (sec, pcm) in enumerate(chunks):
        ready += sec
        if i == 0:
            play_end = ready
        elif ready > play_end:
            stall += ready - play_end
            play_end = ready
        play_end += len(pcm) / 2 / audio.RATE
    return stall


def summarize(values: list[float]) -> dict:
    ms = [v * 1000 for v in values]
    return {"median_ms": round(statistics.median(ms)), "p90_ms": round(p90(ms)),
            "min_ms": round(min(ms)), "max_ms": round(max(ms))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--texts", required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--keep", metavar="DIR", help="1 周目の全文の合成音を DIR に WAV で残す")
    args = parser.parse_args()

    load_env()
    texts = [t.strip() for t in Path(args.texts).read_text().splitlines() if t.strip() and not t.startswith("#")]
    http = httpx.Client(timeout=60)
    stt = GoogleSTT(http)
    stt.model = "latest_long"  # latest_short は長い文章の途中で認識を打ち切ることがある

    t0 = time.monotonic()
    tts = make_tts(http)
    load_s = time.monotonic() - t0

    whole, first, stalls, rtfs = [], [], [], []
    err = total = kerr = ktotal = 0
    rows = []
    for i in range(args.repeat):
        for n, text in enumerate(texts):
            sec, pcm = timed(tts, text)
            chunks = [timed(tts, s) for s in split_sentences(text)]
            dur = len(pcm) / 2 / audio.RATE
            stall = stall_sec(chunks)
            if i == 0:
                hyp = stt.transcribe(pcm)
                e, c = edit_distance(normalize(text), normalize(hyp)), len(normalize(text))
                ke, kc = edit_distance(kana(text), kana(hyp)), len(kana(text))
                err, total, kerr, ktotal = err + e, total + c, kerr + ke, ktotal + kc
                rows.append({"text": text, "hyp": hyp, "errors": e, "chars": c, "kana_errors": ke, "kana_chars": kc})
                if args.keep:
                    Path(args.keep).mkdir(parents=True, exist_ok=True)
                    audio.write_wav_mono(str(Path(args.keep) / f"{tts.voice}-{n + 1}.wav"), pcm)
            # 1 件目はモデルの暖機（クラウドは TLS 接続の確立）を含むので除く
            if (i, n) != (0, 0):
                whole.append(sec)
                first.append(chunks[0][0])
                stalls.append(stall)
                rtfs.append(sec / dur)
            print(f"[{i + 1}/{args.repeat}] 全文 {sec * 1000:5.0f} ms  1 文目 {chunks[0][0] * 1000:5.0f} ms"
                  f"  無音 {stall * 1000:5.0f} ms  音声 {dur:4.1f} s  {len(text)} 文字"
                  + (f"  誤り {rows[-1]['errors']}/{rows[-1]['chars']}" if i == 0 else ""))
            if i == 0:
                print(f"    元: {text}\n    認識: {rows[-1]['hyp']}")

    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    summary = {"ts": datetime.now().isoformat(timespec="seconds"), "voice": tts.voice,
               "n": len(whole), "load_s": round(load_s, 2), "rss_mb": round(rss_mb),
               "whole": summarize(whole), "first": summarize(first),
               "stall_median_ms": round(statistics.median(stalls) * 1000),
               "stall_max_ms": round(max(stalls) * 1000),
               "rtf": round(statistics.median(rtfs), 3),
               "cer": round(err / total, 3), "errors": err, "chars": total,
               "kana_cer": round(kerr / ktotal, 3), "kana_errors": kerr, "kana_chars": ktotal,
               "results": rows}
    w, f = summary["whole"], summary["first"]
    print(f"\n{tts.voice}: 全文 {w['median_ms']} / {w['p90_ms']} ms  1 文目 {f['median_ms']} / {f['p90_ms']} ms"
          f"（中央値 / p90）  無音 中央値 {summary['stall_median_ms']} ms・最大 {summary['stall_max_ms']} ms"
          f"  RTF {summary['rtf']}  CER {summary['cer']:.1%}（{err}/{total}）"
          f"  かな CER {summary['kana_cer']:.1%}（{kerr}/{ktotal}）"
          f"  読み込み {summary['load_s']} s  メモリ {summary['rss_mb']} MB")
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as fp:
        fp.write(json.dumps(summary, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
