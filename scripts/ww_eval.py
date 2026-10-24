#!/usr/bin/env python3
"""学習したウェイクワードのモデルを、学習に使っていない音で評価する（段階 3 の手順 3。WSL で .venv-ww を使う）

使い方（WSL、リポジトリ直下で。先に ww_train.py）:
  .venv-ww/bin/python scripts/ww_eval.py
  .venv-ww/bin/python scripts/ww_eval.py --model cache/wakeword/smoke/r2d2.onnx --train cache/wakeword/smoke
見るもの（しきい値ごと）:
  見逃し率      検証用の陽性（合成音声）を、前後に間を入れ背景音を混ぜて 80 ms ずつ流し、一度も超えなかった割合
  似た音の誤検知  検証用の陰性（「アールツー」など）で超えた割合
  誤検知/時間    openWakeWord の検証用の特徴量（約 11 時間）で超えた回数。超えてから 2 秒は数えない
推論は Pi と同じ openWakeWord の Model（ONNX）を使う。誤検知/時間だけは特徴量から直接判定器に通す。
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant.audio import RATE  # noqa: E402
from assistant.config import ROOT  # noqa: E402

OWW = ROOT / "cache" / "wakeword" / "openWakeWord"
DATA = ROOT / "cache" / "wakeword" / "data"
CHUNK = 1280  # 80 ms。openWakeWord の 1 回の入力
THRESHOLDS = [0.3, 0.5, 0.7, 0.9]


def mix(x: np.ndarray, noise: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    """前に 1 秒・後ろに 0.5 秒の間を足し、背景音を SNR で混ぜる"""
    x = np.concatenate([np.zeros(RATE), x, np.zeros(RATE // 2)])
    if len(noise) < len(x):
        noise = np.tile(noise, len(x) // len(noise) + 1)
    start = rng.integers(len(noise) - len(x) + 1)
    n = noise[start:start + len(x)]
    gain = np.sqrt(np.mean(x ** 2) / (np.mean(n ** 2) + 1e-12) / 10 ** (snr_db / 10))
    return x + gain * n


def max_score(model, x: np.ndarray, name: str) -> float:
    model.reset()
    pcm = np.clip(x * 32768, -32768, 32767).astype(np.int16)
    best = 0.0
    for i in range(0, len(pcm) - CHUNK + 1, CHUNK):
        best = max(best, float(model.predict(pcm[i:i + CHUNK])[name]))
    return best


def fp_per_hour(onnx_path: Path) -> dict:
    import onnxruntime as ort

    feats = np.load(DATA / "validation.npy").astype(np.float32)
    session = ort.InferenceSession(str(onnx_path))
    x = session.get_inputs()[0]
    n = x.shape[1]
    # 書き出したモデルは 1 度に 1 窓（Pi では 80 ms ごとに 1 窓ずつ判定する）
    scores = np.array([session.run(None, {x.name: feats[None, i:i + n]})[0][0, 0] for i in range(len(feats) - n + 1)])
    hours = len(feats) * CHUNK / RATE / 3600
    result = {"hours": round(hours, 1)}
    for t in THRESHOLDS:
        count, last = 0, -10 ** 9
        for i in np.flatnonzero(scores >= t):
            if i - last >= 25:  # 25 フレーム = 2 秒
                count += 1
                last = i
        result[t] = round(count / hours, 2)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="cache/wakeword/train/r2d2.onnx")
    ap.add_argument("--train", default="cache/wakeword/train", help="ww_train.py の --out（検証用の音の場所）")
    ap.add_argument("--synth", default="cache/wakeword/synth", help="ww_synth.py の --out（声の内訳を見る）")
    ap.add_argument("--snr", type=float, nargs=2, default=[5, 20], help="背景音を混ぜる SNR の範囲（dB）")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    sys.path.insert(0, str(OWW))
    from openwakeword.model import Model

    onnx_path = ROOT / args.model
    model = Model(wakeword_models=[str(onnx_path)], inference_framework="onnx")
    name = onnx_path.stem
    rng = np.random.default_rng(args.seed)
    background = sorted((DATA / "background").glob("*.wav"))
    voice = {Path(r["file"]).name: r["voice"] for r in map(json.loads, open(ROOT / args.synth / "manifest.jsonl"))
             if r["label"] == "positive"}

    scores = {}
    for label in ["positive", "negative"]:
        files = sorted((ROOT / args.train / "r2d2" / f"{label}_test").glob("*.wav"))  # 名前を変えたモデルも同じ検証用の音で測る
        s = []
        for f in files:
            x, _ = sf.read(f, dtype="float32")
            noise, _ = sf.read(background[rng.integers(len(background))], dtype="float32")
            s.append((f.name, max_score(model, mix(x, noise, rng.uniform(*args.snr), rng), name)))
        scores[label] = s

    fp = fp_per_hour(onnx_path)
    print(f"検証用: 陽性 {len(scores['positive'])} 本・陰性 {len(scores['negative'])} 本（背景音 SNR {args.snr[0]:g}〜{args.snr[1]:g} dB）、"
          f"誤検知の検証 {fp['hours']} 時間")
    print("| しきい値 | 見逃し率 | 似た音の誤検知 | 誤検知/時間 |")
    print("|---:|---:|---:|---:|")
    for t in THRESHOLDS:
        miss = np.mean([v < t for _, v in scores["positive"]])
        fa = np.mean([v >= t for _, v in scores["negative"]])
        print(f"| {t} | {miss:.1%} | {fa:.1%} | {fp[t]} |")

    by_voice = defaultdict(list)
    for f, v in scores["positive"]:
        by_voice[voice.get(f, "?")].append(v < 0.5)
    print("声ごとの見逃し率（しきい値 0.5）:", "、".join(f"{v} {np.mean(m):.0%}（{len(m)} 本）" for v, m in
                                       sorted(by_voice.items(), key=lambda kv: -np.mean(kv[1]))))


if __name__ == "__main__":
    main()
