"""ウェイクワード「R2D2」で聞き始める（段階 3）。モデルは WSL で scripts/ww_train.py で作り、models/wakeword/ に置く

listen() は arecord を流したまま ch1 を 80 ms ずつ openWakeWord に渡し、検知したら合図音を鳴らして、
そのまま話し終わる（無音が続く）まで録った PCM を返す。返す前に arecord を止めるので、回答の再生中は聞かない
（自分の再生音で反応しない）。確認役（custom verifier）があれば、本体が反応したときに自分の声かを確かめる。
"""
import os
import subprocess
import threading
import time

import numpy as np

from . import audio
from .config import ROOT

MODELS = ROOT / "models" / "wakeword"
MODEL = MODELS / "r2d2.onnx"
VERIFIER = MODELS / "r2d2_verifier.pkl"  # scripts/ww_verifier.py（WSL）で作る。ww_enroll.py（Pi）でも作れるが、誤検知が多い
CHUNK = 1280  # 80 ms。openWakeWord の 1 回の入力


def beep(freq: float = 880, sec: float = 0.12) -> bytes:
    t = np.arange(int(audio.RATE * sec)) / audio.RATE
    fade = np.minimum(1, np.minimum(t, sec - t) / 0.01)  # 端を 10 ms で丸めてプツッと鳴らないようにする
    return (0.3 * 32767 * fade * np.sin(2 * np.pi * freq * t)).astype(np.int16).tobytes()


def play_async(pcm: bytes) -> None:
    """鳴らし終わりを待たずに戻る（録音はそのまま続ける）"""
    def run():
        player = audio.Player()
        player.write(pcm)
        player.close()
    threading.Thread(target=run, daemon=True).start()


def rms_db(pcm: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)) + 1e-9)


class Listener:
    def __init__(self):
        from openwakeword.model import Model

        # 既定値は WSL での評価（scripts/ww_verifier.py）で、確認役ありで誤検知が 1 時間に 0.1 回を切った値
        self.threshold = float(os.environ.get("WAKEWORD_THRESHOLD", "0.95"))
        self.silence_sec = float(os.environ.get("WAKEWORD_SILENCE_MS", "1200")) / 1000  # この長さ無音が続いたら止める
        self.max_sec = float(os.environ.get("WAKEWORD_MAX_SEC", "10"))  # 話し続けてもここで止める
        self.margin_db = float(os.environ.get("WAKEWORD_SPEECH_DB", "6"))  # 雑音の床よりこれだけ大きければ話している
        self.wait_sec = float(os.environ.get("WAKEWORD_WAIT_SEC", "4"))  # 検知のあと、話し始めるまでこれだけ待つ
        verifier = {}
        if VERIFIER.exists() and os.environ.get("WAKEWORD_VERIFIER", "1") == "1":
            verifier = {MODEL.stem: str(VERIFIER)}
        self.model = Model(wakeword_models=[str(MODEL)], inference_framework="onnx",
                           custom_verifier_models=verifier,
                           custom_verifier_threshold=float(os.environ.get("WAKEWORD_VERIFIER_THRESHOLD", "0.5")))
        self.verifier = bool(verifier)

    def chunks(self, proc: subprocess.Popen):
        """arecord の出力を 80 ms ずつ ch1 の int16 にして返す"""
        size = CHUNK * audio.CHANNELS * 2
        while len(raw := proc.stdout.read(size)) == size:
            yield np.frombuffer(audio.extract_channel(raw, audio.CHANNELS, audio.VOICE_CHANNEL), np.int16)

    def listen(self, log=print) -> tuple[bytes, float, float]:
        """呼びかけを待って話を録る。(PCM, 録り終えた時刻, 検知したときのスコア) を返す"""
        proc = subprocess.Popen(["arecord", "-D", audio.DEVICE, "-q", "-t", "raw", "-f", "S16_LE",
                                 "-r", str(audio.RATE), "-c", str(audio.CHANNELS)], stdout=subprocess.PIPE)
        try:
            self.model.reset()
            floor = []  # 待っている間の音量（dB）。雑音の床を見積もる
            chunks = self.chunks(proc)
            for pcm in chunks:
                score = float(self.model.predict(pcm)[MODEL.stem])
                floor = (floor + [rms_db(pcm)])[-50:]  # 直近 4 秒
                if score >= self.threshold:
                    break
            else:
                raise RuntimeError("録音が止まった（arecord を確認）")
            log(f"  検知（スコア {score:.2f}）")
            play_async(beep())

            # 検知した後の音を録る。話し始めてから無音が silence_sec 続いたら止める（話し始めなければ wait_sec で諦める）
            floor_db = np.percentile(floor, 20)
            speech_db = floor_db + self.margin_db
            recorded, quiet, spoke, loudest = [], 0.0, False, -200.0
            for pcm in chunks:
                recorded.append(pcm)
                db = rms_db(pcm)
                loudest = max(loudest, db)
                if db >= speech_db:
                    spoke, quiet = True, 0.0
                else:
                    quiet += CHUNK / audio.RATE
                sec = len(recorded) * CHUNK / audio.RATE
                if (spoke and quiet >= self.silence_sec) or (not spoke and sec >= self.wait_sec) or sec >= self.max_sec:
                    break
            t_end = time.monotonic()
            log(f"  録音 {sec:.1f} 秒（床 {floor_db:.0f} dB、話しているとみなす {speech_db:.0f} dB 以上、いちばん大きい音 {loudest:.0f} dB）")
        finally:
            proc.terminate()
            proc.wait()
        return np.concatenate(recorded).tobytes() if spoke else b"", t_end, score
