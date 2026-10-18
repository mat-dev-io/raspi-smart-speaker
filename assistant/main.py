"""段階 1: Enter キー → 録音 → Google STT → Claude → Google TTS → 再生

使い方（Pi 上、リポジトリ直下で）:
  .venv/bin/python -m assistant.main                         # マイク。Enter で録音開始・終了
  .venv/bin/python -m assistant.main --save recordings       # マイク。録音を WAV で保存する
  .venv/bin/python -m assistant.main --wav recordings/*.wav --repeat 3   # 録音済み WAV で計測
各区間の時間は logs/latency.jsonl に 1 行ずつ追記する。
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import httpx

from . import audio
from .config import ROOT, load_env
from .llm import Claude
from .stt import make_stt
from .tts import GoogleTTS

LOG = ROOT / "logs" / "latency.jsonl"


def ms(start: float, end: float) -> int:
    return round((end - start) * 1000)


class Pipeline:
    def __init__(self):
        self.http = httpx.Client(timeout=30)
        self.stt = make_stt(self.http)
        self.llm = Claude()
        self.tts = GoogleTTS(self.http)

    def run(self, pcm: bytes, source: str, t_end: float) -> None:
        """t_end は録音を終えた時刻（遅延の起点）"""
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "source": source,
               "rec_sec": round(len(pcm) / 2 / audio.RATE, 2),
               "model": self.llm.model, "effort": self.llm.effort,
               "stt_model": self.stt.model, "voice": self.tts.voice}

        text = self.stt.transcribe(pcm)
        t_stt = time.monotonic()
        print(f"あなた: {text or '（聞き取れず）'}")
        if not text:
            return

        reply = self.llm.ask(text)
        t_llm = time.monotonic()
        print(f"Claude: {reply}")

        wav = self.tts.synthesize(reply)
        t_tts = time.monotonic()

        played = {}
        audio.play_wav(wav, on_start=lambda: played.setdefault("t", time.monotonic()))

        rec.update(stt_ms=ms(t_end, t_stt), llm_ms=ms(t_stt, t_llm), tts_ms=ms(t_llm, t_tts),
                   play_ms=ms(t_tts, played["t"]), total_ms=ms(t_end, played["t"]),
                   reply_sec=round(audio.wav_seconds(wav), 2), reply_chars=len(reply),
                   transcript=text, reply=reply)
        print(f"  遅延 合計 {rec['total_ms']} ms（STT {rec['stt_ms']} / LLM {rec['llm_ms']}"
              f" / TTS {rec['tts_ms']} / 再生開始 {rec['play_ms']}）")
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def mic_loop(pipe: Pipeline, save_dir: str | None) -> None:
    recorder = audio.Recorder()
    n = 0
    while True:
        if input("\nEnter で録音開始（q で終了）> ").strip().lower() == "q":
            return
        recorder.start()
        input("録音中… 話し終えたら Enter > ")
        t_end = time.monotonic()
        pcm = recorder.stop()
        n += 1
        if save_dir:
            Path(save_dir).mkdir(parents=True, exist_ok=True)
            path = Path(save_dir) / f"{datetime.now():%Y%m%d-%H%M%S}.wav"
            audio.write_wav_mono(str(path), pcm)
            print(f"  保存: {path}")
        pipe.run(pcm, "mic", t_end)


def wav_bench(pipe: Pipeline, paths: list[str], repeat: int) -> None:
    for i in range(repeat):
        for path in paths:
            print(f"\n== [{i + 1}/{repeat}] {path}")
            pcm = audio.read_wav_mono(path)
            pipe.run(pcm, f"wav:{Path(path).name}", time.monotonic())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wav", nargs="+", help="マイクの代わりに使う WAV（16 kHz / 16bit）")
    parser.add_argument("--repeat", type=int, default=1, help="--wav を何周するか")
    parser.add_argument("--save", metavar="DIR", help="マイクの録音を DIR に WAV で保存する")
    args = parser.parse_args()

    load_env()
    pipe = Pipeline()
    try:
        if args.wav:
            wav_bench(pipe, args.wav, args.repeat)
        else:
            mic_loop(pipe, args.save)
    except (KeyboardInterrupt, EOFError):
        print()


if __name__ == "__main__":
    main()
