#!/usr/bin/env python3
"""ウェイクワードの確認役（openWakeWord の custom verifier）を、誤検知しやすい音も陰性に入れて作る（段階 3。WSL で .venv-ww を使う）

使い方（WSL、リポジトリ直下で。先に ww_train.py --own）:
  .venv-ww/bin/python scripts/ww_verifier.py
  scp cache/wakeword/train/r2d2_verifier.pkl raspi:raspi-smart-speaker/models/wakeword/
ww_enroll.py（Pi）の確認役は、陰性が自分の話し声 60 秒だけなので、テレビや音楽のような音を「自分の声でない」と学べない。
ここでは openWakeWord と同じ作り（ロジスティック回帰）で、陰性に次も足す:
  - 学習用の陰性の特徴量（ACAV100M、約 2,000 時間）のうち、本体のスコアが --mine 以上になった窓
陽性は自分の声のうち ww_train.py が検証用（own_test）に取っておかなかった分。own_test と誤検知の検証用の特徴量で評価する。
"""
import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant.config import ROOT  # noqa: E402

OWW = ROOT / "cache" / "wakeword" / "openWakeWord"
DATA = ROOT / "cache" / "wakeword" / "data"
CHUNK = 1280


def windows(model, name: str, x: np.ndarray, min_score: float, offsets: int, rng) -> list[np.ndarray]:
    """音を 80 ms ずつ流し、本体のスコアが min_score 以上になったところの特徴（16 × 96）を集める。
    offsets 回、始まりを少しずらして流す（openWakeWord の get_reference_clip_features と同じ）"""
    out = []
    pcm = np.clip(np.concatenate([np.zeros(16000), x, np.zeros(8000)]) * 32768, -32768, 32767).astype(np.int16)
    for _ in range(offsets):
        model.reset()
        start = rng.integers(CHUNK) if offsets > 1 else 0
        for i in range(start, len(pcm) - CHUNK + 1, CHUNK):
            if model.predict(pcm[i:i + CHUNK])[name] >= min_score:
                out.append(model.preprocessor.get_features(model.model_inputs[name])[0])
    return out


def base_scores(session, x: np.ndarray) -> np.ndarray:
    inp = session.get_inputs()[0].name
    return np.array([session.run(None, {inp: x[i:i + 1].astype(np.float32)})[0][0, 0] for i in range(len(x))])


def events_per_hour(scores: np.ndarray, threshold: float, hours: float) -> float:
    count, last = 0, -10 ** 9
    for i in np.flatnonzero(scores >= threshold):
        if i - last >= 25:  # 超えてから 2 秒は数えない（ww_eval.py と同じ）
            count += 1
            last = i
    return count / hours


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="cache/wakeword/train")
    ap.add_argument("--own", default="cache/wakeword/own", help="自分の声の陽性")
    ap.add_argument("--own-negative", default="cache/wakeword/own_negative", help="自分の話し声（ww_enroll.py の陰性）")
    ap.add_argument("--mine", type=float, default=0.3, help="ACAV100M から拾う窓の本体のスコア")
    ap.add_argument("--C", type=float, default=0.001, help="ロジスティック回帰の正則化（openWakeWord の既定は 0.001）")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    sys.path.insert(0, str(OWW))
    from openwakeword.custom_verifier_model import flatten_features  # Pi で読み込むとき同じ関数を探すので、これを使う
    from openwakeword.model import Model

    train = ROOT / args.train
    onnx_path = train / "r2d2.onnx"
    name = onnx_path.stem
    model = Model(wakeword_models=[str(onnx_path)], inference_framework="onnx")
    rng = np.random.default_rng(args.seed)
    held_out = {p.name for p in (train / "r2d2" / "own_test").glob("*.wav")}

    pos = []
    for f in sorted((ROOT / args.own).glob("*.wav")):
        if f.name not in held_out:
            pos += windows(model, name, sf.read(f, dtype="float32")[0], 0.5, 5, rng)
    neg_own = []
    for f in sorted((ROOT / args.own_negative).glob("*.wav")):
        neg_own += windows(model, name, sf.read(f, dtype="float32")[0], 0.0, 1, rng)

    session = ort.InferenceSession(str(onnx_path))
    acav = np.load(DATA / "acav100m.npy", mmap_mode="r")
    print(f"ACAV100M の {len(acav)} 窓に本体を通す", flush=True)
    acav_scores = np.concatenate([base_scores(session, np.asarray(acav[i:i + 100000]))
                                  for i in range(0, len(acav), 100000)])
    neg_hard = np.asarray(acav[np.flatnonzero(acav_scores >= args.mine)]).astype(np.float32)
    print(f"陽性 {len(pos)} 窓、陰性 自分の話し声 {len(neg_own)} 窓 + 本体が {args.mine} 以上になった ACAV100M {len(neg_hard)} 窓")

    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import FunctionTransformer, StandardScaler

    features = np.vstack([np.array(pos), np.array(neg_own), neg_hard])
    labels = np.array([1] * len(pos) + [0] * (len(neg_own) + len(neg_hard)))
    # openWakeWord の train_verifier_model と同じ作り。陰性が陽性より桁違いに多いので class_weight で釣り合いを取る
    pipeline = make_pipeline(FunctionTransformer(flatten_features), StandardScaler(),
                             LogisticRegression(random_state=0, max_iter=2000, C=args.C, class_weight="balanced"))
    pipeline.fit(features, labels)
    out = train / "r2d2_verifier.pkl"
    out.write_bytes(pickle.dumps(pipeline))

    # 評価: 誤検知の検証用の特徴量（本体が 0.5 以上 → 確認役のスコアに置き換え、openWakeWord の推論と同じ）と、取っておいた自分の声
    val = np.load(DATA / "validation.npy").astype(np.float32)
    val_win = np.lib.stride_tricks.sliding_window_view(val, (16, val.shape[1]))[:, 0]
    base = base_scores(session, val_win)
    hours = len(val) * CHUNK / 16000 / 3600
    checked = base.copy()
    idx = np.flatnonzero(base >= 0.5)
    checked[idx] = pipeline.predict_proba(val_win[idx])[:, 1]
    with_verifier = Model(wakeword_models=[str(onnx_path)], inference_framework="onnx",
                          custom_verifier_models={name: str(out)}, custom_verifier_threshold=0.5)
    own_scores = {}
    for label, m in [("本体だけ", model), ("確認役あり", with_verifier)]:
        s = []
        for f in sorted((train / "r2d2" / "own_test").glob("*.wav")):
            x = sf.read(f, dtype="float32")[0]
            pcm = np.clip(np.concatenate([np.zeros(16000), x, np.zeros(8000)]) * 32768, -32768, 32767).astype(np.int16)
            m.reset()
            s.append(max(float(m.predict(pcm[i:i + CHUNK])[name]) for i in range(0, len(pcm) - CHUNK + 1, CHUNK)))
        own_scores[label] = np.array(s)
    print(f"| しきい値 | 誤検知/時間 本体だけ | 誤検知/時間 確認役あり | 自分の声の見逃し 本体だけ | 確認役あり（{len(held_out)} 本） |")
    print("|---:|---:|---:|---:|---:|")
    for t in [0.5, 0.7, 0.9, 0.95, 0.99]:
        print(f"| {t} | {events_per_hour(base, t, hours):.2f} | {events_per_hour(checked, t, hours):.2f} | "
              f"{np.mean(own_scores['本体だけ'] < t):.0%} | {np.mean(own_scores['確認役あり'] < t):.0%} |")
    print(f"出力: {out}（誤検知の検証 {hours:.1f} 時間）")


if __name__ == "__main__":
    main()
