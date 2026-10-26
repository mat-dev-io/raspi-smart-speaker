#!/usr/bin/env python3
"""自分の声を録って、ウェイクワードの確認役（openWakeWord の custom verifier）を作る（段階 3。Pi で実行する）

使い方（Pi 上、リポジトリ直下で。先に models/wakeword/r2d2.onnx を置く）:
  .venv/bin/python scripts/ww_enroll.py              # 録る → 確認役を作る
  .venv/bin/python scripts/ww_enroll.py --no-record  # 録り直さずに、録ってある音で作り直す
  .venv/bin/python scripts/ww_enroll.py --pos 75 --no-neg   # 陽性だけ録り足す（番号は今ある分の続き）
録るもの（XVF3800 の ch1。実際に使うときと同じ経路）:
  陽性  Enter を押して「R2D2」と 1 回言う。2.5 秒ずつ --pos 本
  陰性  画面の文を普段の調子で読む。--neg 秒（「R2D2」は言わない）
録音は recordings/wakeword/（コミットしない）、確認役は models/wakeword/r2d2_verifier.pkl に書く。
ここで作る確認役は陰性が自分の話し声だけで誤検知が多いので、録音を WSL に持っていき scripts/ww_verifier.py で作り直す。
陽性ごとに本体のモデルのスコアの最大値を出す（確認役は、本体が 0.5 を超えたところの特徴しか使えない）。
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant import audio  # noqa: E402
from assistant.config import ROOT  # noqa: E402
from assistant.wakeword import MODEL, VERIFIER, beep  # noqa: E402

OUT = ROOT / "recordings" / "wakeword"
SENTENCES = [
    "今日はいい天気ですね。午後から少し出かけようと思います。",
    "冷蔵庫に牛乳が残っているか、あとで確かめておいてください。",
    "来週の月曜日は朝九時から会議があるので、早めに起きます。",
    "駅前の新しいパン屋さんは、クロワッサンがおいしいらしいです。",
    "テレビの音が少し大きいので、下げてもらえますか。",
    "アールグレイの紅茶とツナのサンドイッチをください。",
    "ディーゼル車とガソリン車では、どちらが燃費がいいんだろう。",
    "週末は部屋の片付けをして、それから映画を見に行きたいです。",
]


def play_beep() -> None:
    player = audio.Player()
    player.write(beep())
    player.close()


def record(sec: float) -> bytes:
    rec = audio.Recorder()
    rec.start()
    time.sleep(sec)
    return rec.stop()


def max_score(model, path: Path) -> float:
    model.reset()
    return max(float(p[MODEL.stem]) for p in model.predict_clip(str(path)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pos", type=int, default=25, help="陽性の本数")
    ap.add_argument("--neg", type=int, default=60, help="陰性の秒数")
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--no-neg", action="store_true", help="陰性は録らない（録ってある分を使う）")
    args = ap.parse_args()

    from openwakeword.model import Model

    model = Model(wakeword_models=[str(MODEL)], inference_framework="onnx")
    (OUT / "positive").mkdir(parents=True, exist_ok=True)
    (OUT / "negative").mkdir(parents=True, exist_ok=True)
    if not args.no_record:
        print(f"陽性: Enter を押したら、ビープのあと 2.5 秒の間に「R2D2」と 1 回言ってください（{args.pos} 本）。"
              "距離や向き・声の大きさを少しずつ変えると効きやすい")
        start = len(list((OUT / "positive").glob("*.wav")))  # 録ってある分の続きから番号を振る
        for i in range(args.pos):
            input(f"[{i + 1}/{args.pos}] Enter > ")
            play_beep()
            path = OUT / "positive" / f"{start + i:03d}.wav"
            audio.write_wav_mono(str(path), record(2.5))
            print(f"  本体のスコア {max_score(model, path):.2f}")
    if not args.no_record and not args.no_neg:
        input(f"\n陰性: Enter を押したら、下の文を普段の調子で読んでください。{args.neg} 秒で止まります（R2D2 とは言わない）\n"
              + "\n".join(f"  {s}" for s in SENTENCES) + "\nEnter > ")
        play_beep()
        pcm = record(args.neg)
        size = audio.RATE * 2 * 10  # 10 秒ずつに分ける
        for k, j in enumerate(range(0, len(pcm), size)):
            audio.write_wav_mono(str(OUT / "negative" / f"{k:03d}.wav"), pcm[j:j + size])

    positives = sorted((OUT / "positive").glob("*.wav"))
    negatives = sorted((OUT / "negative").glob("*.wav"))
    scores = [max_score(model, p) for p in positives]
    hit = sum(s >= 0.5 for s in scores)
    print(f"\n陽性 {len(positives)} 本のうち、本体が 0.5 を超えたのは {hit} 本（スコアの中央値 {np.median(scores):.2f}）")
    neg_scores = [max_score(model, p) for p in negatives]
    print(f"陰性 {len(negatives)} 本（{len(negatives) * 10} 秒）での本体のスコアの最大値 {max(neg_scores):.2f}")
    if hit < 3:
        raise SystemExit("NG: 本体が反応した陽性が 3 本より少ないので確認役を作れない（本体のモデルを見直す）")

    from openwakeword import train_custom_verifier

    train_custom_verifier(positive_reference_clips=[str(p) for p in positives],
                          negative_reference_clips=[str(p) for p in negatives],
                          output_path=str(VERIFIER), model_name=str(MODEL), inference_framework="onnx")
    print(f"出力: {VERIFIER}")


if __name__ == "__main__":
    main()
