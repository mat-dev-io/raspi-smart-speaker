#!/usr/bin/env python3
"""ウェイクワードの学習（段階 3）に使う公開データを cache/wakeword/data に落とす（WSL で .venv-ww を使う）

使い方（WSL、リポジトリ直下で）:
  .venv-ww/bin/python scripts/ww_fetch_data.py   （済んでいるものは飛ばす。全部で約 20 GB）
落とすもの（どれも Hugging Face から。自宅で使う前提で、モデルもデータも配らない）:
  acav100m.npy    陰性の特徴量。ACAV100M の約 2,000 時間分を openWakeWord の特徴量にしたもの（17 GB、CC BY-NC-SA 4.0）
  validation.npy  誤検知の検証用の特徴量（約 11 時間分、185 MB、同上）
  rirs/           MIT の部屋の残響（271 本、16 kHz）
  background/     背景音。AudioSet の bal_train から PARQUETS 個分（1 個 500 本 × 10 秒）を 16 kHz / mono にしたもの（CC BY 4.0）
"""
import io
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from huggingface_hub import hf_hub_download
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant.audio import RATE  # noqa: E402
from assistant.config import ROOT  # noqa: E402

DATA = ROOT / "cache" / "wakeword" / "data"
RAW = DATA / "raw"
PARQUETS = 3


def fetch(repo: str, name: str, dest: Path) -> None:
    if dest.exists():
        return
    print(f"取得: {repo}/{name}", flush=True)
    Path(hf_hub_download(repo, name, repo_type="dataset", local_dir=RAW)).rename(dest)


def write16k(path: Path, x: np.ndarray, rate: int) -> None:
    if x.ndim == 2:
        x = x.mean(axis=1)
    if rate != RATE:
        x = resample_poly(x, RATE, rate)
    sf.write(path, np.clip(x, -1, 1), RATE, subtype="PCM_16")


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    fetch("davidscripka/openwakeword_features", "openwakeword_features_ACAV100M_2000_hrs_16bit.npy", DATA / "acav100m.npy")
    fetch("davidscripka/openwakeword_features", "validation_set_features.npy", DATA / "validation.npy")

    rirs = DATA / "rirs"
    if not rirs.exists():
        from huggingface_hub import snapshot_download

        print("取得: 残響", flush=True)
        src = Path(snapshot_download("davidscripka/MIT_environmental_impulse_responses", repo_type="dataset",
                                     local_dir=RAW / "mit_rirs", allow_patterns=["16khz/*.wav"]))
        (src / "16khz").rename(rirs)

    background = DATA / "background"
    background.mkdir(exist_ok=True)
    import pyarrow.parquet as pq

    for i in range(PARQUETS):
        done = background / f".done{i:02d}"
        if done.exists():
            continue
        print(f"取得: 背景音 {i + 1}/{PARQUETS}", flush=True)
        path = hf_hub_download("agkphysics/AudioSet", f"data/bal_train/{i:02d}.parquet", repo_type="dataset", local_dir=RAW)
        bad = 0
        for row in pq.read_table(path, columns=["video_id", "audio"]).to_pylist():
            try:
                x, rate = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="float32")
            except sf.LibsndfileError:
                bad += 1
                continue
            write16k(background / f"{row['video_id']}.wav", x, rate)
        done.touch()
        Path(path).unlink()
        print(f"  読めなかった音: {bad} 本", flush=True)

    n = len(list(background.glob("*.wav")))
    print(f"残響 {len(list(rirs.glob('*.wav')))} 本、背景音 {n} 本（約 {n * 10 / 3600:.1f} 時間）")


if __name__ == "__main__":
    main()
