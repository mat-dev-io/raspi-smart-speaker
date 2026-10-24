#!/usr/bin/env python3
"""ウェイクワード「R2D2」の学習データを VOICEVOX で合成する（段階 3。WSL で .venv-ww を使う）

使い方（WSL、リポジトリ直下で。先に scripts/ww_setup.sh）:
  .venv-ww/bin/python scripts/ww_synth.py --pos 12 --neg 6 --out cache/wakeword/trial   # 試しに聞く分
  .venv-ww/bin/python scripts/ww_synth.py --pos 5000 --neg 5000                         # 学習用
1 本ごとに声（スタイル）・読み・速さ・高さ・抑揚を乱数で振る。
陽性はウェイクワード、陰性は一部だけの言葉や似た音。16 kHz / mono の WAV で OUT/positive・OUT/negative に書き、
1 本 1 行の設定を OUT/manifest.jsonl に残す。雑音・残響のかさ増しは学習（openWakeWord）の側でする。
使う声は規約で機械学習の利用を禁止していない 11 体だけ（plans/stage3-wakeword.md の「決まったこと」3）。
"""
import argparse
import io
import json
import sys
import wave
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant.config import ROOT  # noqa: E402
from assistant.tts_local import VOICEVOX, VOICEVOX_DICT, VOICEVOX_ORT, to_wav  # noqa: E402

VOICES = ["東北ずん子", "ずんだもん", "四国めたん", "九州そら", "東北きりたん", "東北イタコ",
          "中国うさぎ", "中部つるぎ", "あんこもん", "波音リツ", "冥鳴ひまり"]

# 読みは AquesTalk 風の記法（' がアクセント核、/ が句の区切り、、が間）。"R2D2" のままだと「アールニディーニ」と読む
POSITIVE = [
    "ア'アルツウディイツウ",
    "アアルツ'ウ/ディイツ'ウ",
    "アアルツ'ウ、ディ'イツウ",
    "ア'アル/ツ'ウ/ディ'イ/ツ'ウ",  # 、で区切ると間が長く 3〜5 秒になるので / で区切る
]
NEGATIVE = [
    "ア'アル", "アアルツ'ウ", "ディ'イツウ", "ツウディ'イ", "アアルツウディ'イ", "ツウディイツ'ウ",
    "アアルディ'イ", "シ'イツウ", "アアルツウシ'イツウ", "エエツウディ'イツウ", "アアルス'リイ",
    "ア'アルツウディイエ", "ディイツウア'アル", "ア'ルトゥウ", "カ'アルツウ", "ア'アト",
]


def load_synth(threads: int):
    from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer, VoiceModelFile

    ort = Onnxruntime.load_once(filename=str(VOICEVOX_ORT))
    synth = Synthesizer(ort, OpenJtalk(str(VOICEVOX_DICT)), cpu_num_threads=threads)
    styles = []  # (声, スタイル名, スタイル ID)
    for path in sorted((VOICEVOX / "models" / "vvms").glob("*.vvm"), key=lambda p: int(p.stem)):
        with VoiceModelFile.open(str(path)) as model:
            found = [(c.name, s.name, s.id) for c in model.metas if c.name in VOICES for s in c.styles]
            if found:
                synth.load_voice_model(model)
                styles += found
    missing = set(VOICES) - {v for v, _, _ in styles}
    if missing:
        raise SystemExit(f"NG: 声が見つからない: {', '.join(sorted(missing))}（scripts/ww_setup.sh を確認）")
    return synth, styles


def synthesize(synth, kana: str, style_id: int, speed: float, pitch: float, intonation: float) -> bytes:
    query = synth.create_audio_query_from_kana(kana, style_id)
    query.speed_scale, query.pitch_scale, query.intonation_scale = speed, pitch, intonation
    with wave.open(io.BytesIO(synth.synthesis(query, style_id))) as w:
        rate = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    return to_wav(x, rate)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pos", type=int, default=12, help="陽性の本数")
    ap.add_argument("--neg", type=int, default=6, help="陰性の本数")
    ap.add_argument("--out", default="cache/wakeword/synth")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--threads", type=int, default=8)
    args = ap.parse_args()

    synth, styles = load_synth(args.threads)
    rng = np.random.default_rng(args.seed)
    out = ROOT / args.out
    voices = Counter()
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "manifest.jsonl", "w") as log:
        for label, n, texts in [("positive", args.pos, POSITIVE), ("negative", args.neg, NEGATIVE)]:
            (out / label).mkdir(exist_ok=True)
            for i in range(n):
                voice, style, style_id = styles[rng.integers(len(styles))]
                rec = {"file": f"{label}/{i:05d}.wav", "label": label, "kana": texts[rng.integers(len(texts))],
                       "voice": voice, "style": style, "style_id": style_id,
                       # 高さは下げる側に広く振る（11 体は高い声が多いので、低い声を補う）
                       "speed": round(rng.uniform(0.8, 1.3), 3), "pitch": round(rng.uniform(-0.15, 0.06), 3),
                       "intonation": round(rng.uniform(0.7, 1.4), 3)}
                wav = synthesize(synth, rec["kana"], style_id, rec["speed"], rec["pitch"], rec["intonation"])
                (out / rec["file"]).write_bytes(wav)
                log.write(json.dumps(rec, ensure_ascii=False) + "\n")
                voices[label, voice] += 1
                if (i + 1) % 500 == 0:
                    print(f"{label} {i + 1}/{n}", flush=True)

    for label in ["positive", "negative"]:
        print(label, sum(c for (l, _), c in voices.items() if l == label), "本:",
              " ".join(f"{v} {voices[label, v]}" for v in VOICES if voices[label, v]))
    print(f"出力: {out}（クレジット: VOICEVOX:{'・'.join(VOICES)}）")


if __name__ == "__main__":
    main()
