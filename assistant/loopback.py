"""音のループバックテスト: 既知の文を TTS → スピーカー → マイク（ch2）→ STT と通し、元の文と照合する

使い方（Pi 上、リポジトリ直下で。WSL からは ./scripts/loopback.sh）:
  .venv/bin/python -m assistant.loopback                    # 全文を流して合否を出す
  .venv/bin/python -m assistant.loopback --inject dropout   # 録音をわざと壊して、不合格になるか確かめる
  .venv/bin/python -m assistant.loopback --keep recordings/loopback   # 録音を WAV で残す
終了コード: 0 = 合格 / 1 = 不合格 / 2 = 環境エラー（デバイスがない・API が失敗した など）

ch1・ch2 とも既定ではエコーキャンセル後の信号で、自分の再生音は消される。
そこでテスト中だけ ch2 をエコーキャンセル前のマイクに切り替え、終わったら元に戻す。
TTS の音声は cache/loopback/ に保存し、2 回目以降は同じ音を流す。
"""
import argparse
import hashlib
import io
import sys
import time
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import usb.core

from . import audio, xvf
from .config import ROOT, load_env
from .stt import GoogleSTT
from .tts import GoogleTTS

# 表記ゆれ（数字・かな/漢字）や同音異義語（公園/公演 など）が出にくい文を選ぶ
SENTENCES = [
    "おはようございます。",
    "今日は朝から雨が降っています。",
    "駅前の本屋で料理の本を買いました。",
    "窓を開けると冷たい風が入ってきました。",
    "明日は早く起きて犬と散歩しようと思います。",
]

CACHE = ROOT / "cache" / "loopback"
LEAD_SEC = 0.5  # 録音を始めてから再生するまで（この区間で雑音の床を測る）
TAIL_SEC = 0.8  # 再生が終わってから録音を止めるまで
FRAME = audio.RATE // 100  # 10 ms
BAND = (250, 4000)  # 信号の比較と STT に使う帯域（Hz）
STT_RMS_DB = -20.0  # STT に渡す音量

# 合格の条件（文ごと）
MIN_SIMILARITY = 0.9  # 文字起こしと元の文の一致度
# 2026-10-18 の実測（docs/c1-loopback.md）: 正常は SNR 15〜21 dB・相関 0.85〜0.91・途切れ 70 ms 以下。
# 壊した録音は 無音/雑音で SNR 0.2 以下・相関 0.12 以下、途切れ（0.2 秒ずつ）で相関 0.68 以下・途切れ 140 ms 以上。
# スピーカーの音量つまみを下げると SNR と相関が落ちて不合格になる（それも「聞こえていない」として正しい）
MIN_SNR_DB = 8.0  # 再生中の音量と雑音の床の差。これ未満は無音とみなす
MIN_ENV_CORR = 0.78  # 元の音声と録音の音量の推移の相関。雑音や途切れで下がる
MAX_GAP_MS = 100  # 元の音声が鳴っているのに録音が床まで落ちた区間の最長
GAP_MARGIN_DB = 3.0  # 床 + これ未満を「落ちた」とみなす
ATTEMPTS = 2  # 1 文を最大何回流すか

INJECTIONS = ["silence", "noise", "dropout"]


# --- 照合 -------------------------------------------------------------------

def normalize(text: str) -> str:
    """句読点・記号・空白を除き、全角/半角をそろえる"""
    text = unicodedata.normalize("NFKC", text)
    return "".join(c for c in text if unicodedata.category(c)[0] not in "PSZ" and not c.isspace())


def similarity(ref: str, hyp: str) -> float:
    """1 - 編集距離 / 長い方の文字数"""
    a, b = normalize(ref), normalize(hyp)
    if not a and not b:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1 - prev[-1] / max(len(a), len(b))


# --- 信号の比較 ---------------------------------------------------------------

def to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, np.int16).astype(np.float64) / 32768


def bandpass(x: np.ndarray) -> np.ndarray:
    """BAND の外を落とす。部屋の雑音は 150 Hz 未満に集中していて、再生音は 300〜1200 Hz で強い"""
    spec = np.fft.rfft(x)
    freq = np.fft.rfftfreq(len(x), 1 / audio.RATE)
    spec[(freq < BAND[0]) | (freq > BAND[1])] = 0
    return np.fft.irfft(spec, len(x))


def for_stt(pcm: bytes) -> bytes:
    """STT に渡す前に帯域を絞り、音量をそろえる。生のマイクは小さく低音の雑音が多く、そのままだと空の結果が返ることがある"""
    x = bandpass(to_float(pcm))
    rms = np.sqrt(np.mean(x ** 2))
    if rms:
        x *= min(10 ** (STT_RMS_DB / 20) / rms, 0.9 / np.abs(x).max())
    return (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()


def envelope_db(x: np.ndarray) -> np.ndarray:
    """10 ms ごとのパワー（dBFS、下限 -100）"""
    frames = x[: len(x) // FRAME * FRAME].reshape(-1, FRAME)
    return 10 * np.log10(np.maximum((frames ** 2).mean(axis=1), 1e-10))


def mean_db(env: np.ndarray) -> float:
    """dB のまま平均すると小さい方に引っ張られるので、パワーで平均する"""
    return float(10 * np.log10(np.mean(10 ** (env / 10))))


@dataclass
class Signal:
    lag_ms: int  # 録音開始から元の音声が現れるまで（LEAD_SEC を含む）
    floor_db: float  # 再生前の雑音の床
    snr_db: float  # 元の音声が鳴っている区間の平均 - 床
    env_corr: float  # 元の音声と録音の音量の推移の相関
    gap_ms: int  # 元の音声が鳴っているのに録音が床まで落ちた区間の最長


def compare(ref_pcm: bytes, rec_pcm: bytes) -> Signal:
    ref = envelope_db(bandpass(to_float(ref_pcm)))
    rec = envelope_db(bandpass(to_float(rec_pcm)))
    lead = rec[2:int(LEAD_SEC * 100) - 5]  # 録音の立ち上がりと再生の直前は避ける
    floor = float(np.median(lead))

    # 音量の推移が一番よく重なるずれを探す（細かい揺れは床・ピーク -40 dB で切る）
    peak = ref.max()
    ref_c = np.maximum(ref, peak - 40)
    rec_c = np.maximum(rec, floor)
    with np.errstate(invalid="ignore"):  # 録音が一定（無音）だと相関は定義されない
        corrs = [np.corrcoef(ref_c, rec_c[lag:lag + len(ref)])[0, 1] for lag in range(len(rec) - len(ref) + 1)]
    corrs = np.nan_to_num(corrs)
    lag = int(np.argmax(corrs))

    active = ref >= peak - 25  # 元の音声が鳴っている（ピークから 25 dB 以内）
    aligned = rec[lag:lag + len(ref)]
    run = longest = 0
    for dropped in active & (aligned < floor + GAP_MARGIN_DB):
        run = run + 1 if dropped else 0
        longest = max(longest, run)

    return Signal(lag_ms=lag * 10, floor_db=round(floor, 1),
                  snr_db=round(mean_db(aligned[active]) - mean_db(lead), 1),
                  env_corr=round(float(corrs[lag]), 2), gap_ms=longest * 10)


# --- 故障の注入 -------------------------------------------------------------

def inject(kind: str, pcm: bytes) -> bytes:
    x = np.frombuffer(pcm, np.int16).copy()
    if kind == "silence":  # 何も入っていない
        x[:] = 0
    elif kind == "noise":  # 同じ音量の雑音にすり替わる
        rms = np.sqrt(np.mean(x.astype(np.float64) ** 2))
        x = np.clip(np.random.default_rng(0).normal(0, rms, len(x)), -32768, 32767).astype(np.int16)
    elif kind == "dropout":  # 0.5 秒ごとに 0.2 秒ずつ途切れる
        x[np.arange(len(x)) % (audio.RATE // 2) < audio.RATE // 5] = 0
    return x.tobytes()


# --- 実行 -------------------------------------------------------------------

def reference_wav(tts: GoogleTTS, text: str) -> bytes:
    """TTS の音声。声と文が同じならキャッシュを使う"""
    key = hashlib.sha1(f"{tts.voice}\n{text}".encode()).hexdigest()[:12]
    path = CACHE / f"{key}.wav"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(tts.synthesize(text))
    return path.read_bytes()


def play_and_record(wav: bytes) -> bytes:
    recorder = audio.Recorder()
    recorder.start()
    time.sleep(LEAD_SEC)
    audio.play_wav(wav)
    time.sleep(TAIL_SEC)
    pcm = recorder.stop(audio.LOOPBACK_CHANNEL)
    if len(pcm) < audio.RATE * 2 * LEAD_SEC:
        raise RuntimeError("録音できなかった（デバイスがない・他のプロセスが使っている など）")
    return pcm


def wav_pcm(wav: bytes) -> bytes:
    with wave.open(io.BytesIO(wav)) as w:
        return w.readframes(w.getnframes())


def judge(sim: float, sig: Signal) -> list[str]:
    """不合格の理由（空なら合格）"""
    reasons = []
    if sig.snr_db < MIN_SNR_DB:
        reasons.append(f"無音（SNR {sig.snr_db} < {MIN_SNR_DB} dB）")
    if sig.env_corr < MIN_ENV_CORR:
        reasons.append(f"元の音声と形が違う（相関 {sig.env_corr} < {MIN_ENV_CORR}）")
    if sig.gap_ms > MAX_GAP_MS:
        reasons.append(f"途切れ（{sig.gap_ms} > {MAX_GAP_MS} ms）")
    if sim < MIN_SIMILARITY:
        reasons.append(f"文字起こしが違う（一致度 {sim:.2f} < {MIN_SIMILARITY}）")
    return reasons


def run(inject_kind: str | None, keep: str | None) -> bool:
    http = httpx.Client(timeout=30)
    tts, stt = GoogleTTS(http), GoogleSTT(http)
    print(f"== ループバックテスト（{len(SENTENCES)} 文、ch{audio.LOOPBACK_CHANNEL + 1} で録音"
          f"{f'、故障注入 {inject_kind}' if inject_kind else ''}）")
    passed = 0
    for n, text in enumerate(SENTENCES, 1):
        wav = reference_wav(tts, text)
        # STT はまれに 1 語読み違える（20 文に 1 回ほど）。壊れた音は流し直しても落ちるので、1 回だけ流し直す
        for attempt in range(1, ATTEMPTS + 1):
            with xvf.right_channel(xvf.RAW_MIC):
                rec = play_and_record(wav)
            if inject_kind:
                rec = inject(inject_kind, rec)
            if keep:
                Path(keep).mkdir(parents=True, exist_ok=True)
                audio.write_wav_mono(str(Path(keep) / f"{n}-{attempt}.wav"), rec)
            hyp = stt.transcribe(for_stt(rec))
            sim = similarity(text, hyp)
            sig = compare(wav_pcm(wav), rec)
            reasons = judge(sim, sig)
            label = f"[{n}]" if attempt == 1 else f"[{n}] 流し直し"
            print(f"{label} {'PASS' if not reasons else 'FAIL'}  一致度 {sim:.2f}  SNR {sig.snr_db} dB"
                  f"  相関 {sig.env_corr}  途切れ {sig.gap_ms} ms  （床 {sig.floor_db} dBFS、遅れ {sig.lag_ms} ms）")
            print(f"    元: {text}")
            print(f"    認識: {hyp or '（なし）'}")
            for r in reasons:
                print(f"    NG: {r}")
            if not reasons:
                passed += 1
                break
    ok = passed == len(SENTENCES)
    print(f"== 結果: {'PASS' if ok else 'FAIL'}（{passed}/{len(SENTENCES)} 文が合格）")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inject", choices=INJECTIONS, help="録音をわざと壊す（不合格になることを確かめる）")
    parser.add_argument("--keep", metavar="DIR", help="録音（ch2）を DIR に WAV で残す")
    args = parser.parse_args()

    load_env()
    try:
        if "[Array " not in Path("/proc/asound/cards").read_text():
            raise RuntimeError("XVF3800 が ALSA に見えない")
        ok = run(args.inject, args.keep)
    except (RuntimeError, OSError, httpx.HTTPError, usb.core.USBError) as e:
        print(f"ERROR: {e}")
        sys.exit(2)
    except SystemExit as e:  # config.require の「未設定」
        print(e.code)
        sys.exit(2)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
