#!/usr/bin/env python3
"""ウェイクワード「R2D2」を openWakeWord で学習する（段階 3。WSL の GPU で .venv-ww を使う）

使い方（WSL、リポジトリ直下で。先に ww_setup.sh・ww_synth.py・ww_fetch_data.py）:
  .venv-ww/bin/python scripts/ww_train.py                  # かさ増し → 特徴量 → 学習
  .venv-ww/bin/python scripts/ww_train.py --steps 10000    # 試しに短く
  .venv-ww/bin/python scripts/ww_train.py --skip-augment   # 特徴量を作り直さずに学習だけやり直す
ww_synth.py の音を 9:1 で学習用と検証用に分けて openWakeWord の学習スクリプト（train.py）に渡す。
Piper での合成の段は使わない。出力は OUT/r2d2.onnx。

train.py は古い torchaudio を前提にしているので、ここで次の手当てをしてから動かす（インストールしたものは書き換えない）:
  - torchaudio.info / load: 新しい版では無いか torchcodec が要るので、soundfile で読む版に差し替える
  - torchaudio.set_audio_backend: 新しい版では無いので何もしない関数を置く（torch_audiomentations が呼ぶ）
  - generate_samples（Piper）: 合成の段を使わないので空のモジュールを置く
  - 検証用の特徴量が float16 のまま判定器に入るので float にする（train.py のソースをメモリ上で置き換える）
  - --convert_to_tflite の既定値が文字列の "False"（真になる）で、使わない TFLite 変換が走って落ちるので止める（同上）
  - 新しい torch は重みを別ファイル（.onnx.data）に書き出すので、Pi に持っていきやすいよう 1 ファイルにまとめる
"""
import argparse
import json
import logging
import sys
import types
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant.audio import RATE  # noqa: E402
from assistant.config import ROOT  # noqa: E402

OWW = ROOT / "cache" / "wakeword" / "openWakeWord"  # ww_setup.sh で取る（コミットを固定）
DATA = ROOT / "cache" / "wakeword" / "data"
MODEL = "r2d2"


def patch_torchaudio() -> None:
    def info(path, *args, **kwargs):
        i = sf.info(str(path))
        return types.SimpleNamespace(num_frames=i.frames, sample_rate=i.samplerate, num_channels=i.channels,
                                     bits_per_sample=16, encoding="PCM_S")

    def load(path, *args, **kwargs):
        x, rate = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(x.T.copy()), rate

    torchaudio.info, torchaudio.load = info, load
    torchaudio.set_audio_backend = lambda *args, **kwargs: None
    sys.modules["generate_samples"] = types.SimpleNamespace(generate_samples=None)


def total_length(clips: list[Path], rng: np.random.Generator) -> int:
    """train.py と同じ決め方（陽性の長さの中央値 + 750 ms、2 秒前後なら 2 秒ちょうど）"""
    median = np.median([sf.info(str(clips[i])).frames for i in rng.integers(len(clips), size=50)])
    n = int(round(median / 1000) * 1000) + 12000
    return 32000 if n < 32000 or abs(n - 32000) <= 4000 else n


def prepare(synth: Path, out: Path, seed: int) -> dict:
    """合成した音を学習用と検証用に分けてリンクを張る。窓より長い陽性は切れて陽性でなくなるので除く"""
    rng = np.random.default_rng(seed)
    clips = {label: sorted((synth / label).glob("*.wav")) for label in ["positive", "negative"]}
    length = total_length(clips["positive"], rng)
    margin = int(0.2 * RATE)  # train.py は末尾を最大 200 ms ずらして置く
    stats = {"total_length": length}
    for label, files in clips.items():
        if label == "positive":
            kept = [f for f in files if sf.info(str(f)).frames <= length - margin]
            stats["positive_too_long"] = len(files) - len(kept)
            files = kept
        files = [files[i] for i in rng.permutation(len(files))]
        n_test = len(files) // 10
        for split, part in [("test", files[:n_test]), ("train", files[n_test:])]:
            d = out / MODEL / f"{label}_{split}"
            d.mkdir(parents=True, exist_ok=True)
            for old in d.glob("*.wav"):
                old.unlink()
            for f in part:
                (d / f.name).symlink_to(f.resolve())
            stats[f"{label}_{split}"] = len(part)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synth", default="cache/wakeword/synth", help="ww_synth.py の出力")
    ap.add_argument("--out", default="cache/wakeword/train")
    ap.add_argument("--steps", type=int, default=50000)
    ap.add_argument("--target-fp", type=float, default=0.1, help="誤検知の目標（1 時間あたり）。完了条件は 10 時間に 1 回")
    ap.add_argument("--rounds", type=int, default=2, help="かさ増しを何周するか")
    ap.add_argument("--layer-size", type=int, default=32, help="判定器の層の幅")
    ap.add_argument("--neg-weight", type=int, default=1500, help="陰性にかける重みの上限（max_negative_weight）")
    ap.add_argument("--adv-batch", type=int, default=50, help="1 回の学習に入れる似た音（陰性）の数")
    ap.add_argument("--skip-augment", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    out = ROOT / args.out
    stats = prepare(ROOT / args.synth, out, args.seed)
    print(json.dumps(stats, ensure_ascii=False))
    config = {
        "model_name": MODEL, "target_phrase": ["R2D2"], "custom_negative_phrases": [],
        "n_samples": stats["positive_train"], "n_samples_val": stats["positive_test"], "tts_batch_size": 1,
        "augmentation_batch_size": 16, "augmentation_rounds": args.rounds,
        "piper_sample_generator_path": str(OWW), "output_dir": str(out),
        "rir_paths": [str(DATA / "rirs")], "background_paths": [str(DATA / "background")],
        "background_paths_duplication_rate": [1],
        "false_positive_validation_data_path": str(DATA / "validation.npy"),
        "feature_data_files": {"ACAV100M_sample": str(DATA / "acav100m.npy")},
        "batch_n_per_class": {"ACAV100M_sample": 1024, "adversarial_negative": args.adv_batch, "positive": 50},
        "model_type": "dnn", "layer_size": args.layer_size, "steps": args.steps,
        "max_negative_weight": args.neg_weight, "target_false_positives_per_hour": args.target_fp,
    }
    config_path = out / f"{MODEL}.yml"
    config_path.write_text(yaml.dump(config, allow_unicode=True))

    patch_torchaudio()
    sys.path.insert(0, str(OWW))
    import openwakeword.utils

    openwakeword.utils.download_models(model_names=["__none__"])  # 特徴抽出の melspectrogram・embedding だけ取る
    train_py = OWW / "openwakeword" / "train.py"
    source = train_py.read_text()
    for old, new in [("val_predictions = self.model(x_val)\n", "val_predictions = self.model(x_val.float())\n"),
                     ("if args.convert_to_tflite:", "if args.convert_to_tflite is True:")]:
        assert old in source, f"train.py が想定と違う（OWW のコミットを確認）: {old.strip()}"
        source = source.replace(old, new)
    sys.argv = [str(train_py), "--training_config", str(config_path), "--train_model"]
    if not args.skip_augment:
        sys.argv.insert(3, "--augment_clips")
    logging.basicConfig(level=logging.INFO)
    exec(compile(source, str(train_py), "exec"), {"__name__": "__main__", "__file__": str(train_py)})

    import onnx

    onnx_path = out / f"{MODEL}.onnx"
    onnx.save(onnx.load(str(onnx_path)), str(onnx_path), save_as_external_data=False)  # .onnx.data の重みを取り込む
    (out / f"{MODEL}.onnx.data").unlink(missing_ok=True)
    print(f"出力: {onnx_path}")


if __name__ == "__main__":
    main()
