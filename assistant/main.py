"""Enter キーか呼びかけ → 録音 → STT → Claude → TTS → 再生（入力・STT・TTS は .env の INPUT / STT_ENGINE / TTS_ENGINE で選ぶ）

使い方（Pi 上、リポジトリ直下で）:
  .venv/bin/python -m assistant.main                         # マイク。Enter で録音開始・終了
  INPUT=wakeword .venv/bin/python -m assistant.main          # マイク。「R2D2」と呼びかけて話す（無音で止まる）
  .venv/bin/python -m assistant.main --save recordings       # マイク。録音を WAV で保存する
  .venv/bin/python -m assistant.main --wav recordings/*.wav --repeat 3   # 録音済み WAV で計測
各区間の時間は logs/latency.jsonl に 1 行ずつ追記する。
回答は 1 文ずつ合成し、1 文目ができたら再生を始める（TTS_SPLIT=0 で段階 1 と同じく全文をまとめて合成する）。
"""
import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import httpx

from . import audio
from .config import ROOT, load_env
from .llm import Claude
from .stt import make_stt
from .tts import make_tts, split_sentences

LOG = ROOT / "logs" / "latency.jsonl"


def ms(start: float, end: float) -> int:
    return round((end - start) * 1000)


class Pipeline:
    def __init__(self):
        self.http = httpx.Client(timeout=30)
        self.stt = make_stt(self.http)
        self.llm = Claude()
        self.tts = make_tts(self.http)
        self.split = os.environ.get("TTS_SPLIT", "1") == "1"

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

        sentences = split_sentences(reply) if self.split else [reply]
        player = audio.Player()  # aplay の起動は合成の間に済ませておく
        reply_sec = stall = 0.0
        try:
            for i, sentence in enumerate(sentences):
                chunk = audio.wav_pcm(self.tts.synthesize(sentence))
                t = time.monotonic()
                if i == 0:
                    t_tts = t_play = t
                else:
                    # 前の文までの再生が終わる予定の時刻より遅れた分は、無音で待たせている
                    stall += max(0.0, t - (t_play + stall + reply_sec))
                player.write(chunk)
                reply_sec += len(chunk) / 2 / audio.RATE
            t_tts_all = time.monotonic()
        finally:
            player.close()

        # tts_ms は 1 文目の合成が終わるまで（TTS_SPLIT=0 なら全文）。tts_all_ms は全文の合成が終わるまで
        rec.update(stt_ms=ms(t_end, t_stt), llm_ms=ms(t_stt, t_llm), tts_ms=ms(t_llm, t_tts),
                   tts_all_ms=ms(t_llm, t_tts_all), stall_ms=round(stall * 1000), sentences=len(sentences),
                   split=self.split, play_ms=ms(t_tts, t_play), total_ms=ms(t_end, t_play),
                   reply_sec=round(reply_sec, 2), reply_chars=len(reply),
                   transcript=text, reply=reply)
        print(f"  遅延 合計 {rec['total_ms']} ms（STT {rec['stt_ms']} / LLM {rec['llm_ms']}"
              f" / TTS {rec['tts_ms']} / 再生開始 {rec['play_ms']}）"
              f"  全文の合成 {rec['tts_all_ms']} ms、途中の無音 {rec['stall_ms']} ms")
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


def wakeword_loop(pipe: Pipeline, save_dir: str | None) -> None:
    from .wakeword import Listener

    listener = Listener()
    print(f"「R2D2」と呼びかけてください（しきい値 {listener.threshold}、確認役 {'あり' if listener.verifier else 'なし'}。"
          "Ctrl+C で終了）")
    while True:
        pcm, t_end, score = listener.listen()
        if not pcm:
            print("  話し始めなかったので待ち直す")
            continue
        if save_dir:
            Path(save_dir).mkdir(parents=True, exist_ok=True)
            path = Path(save_dir) / f"{datetime.now():%Y%m%d-%H%M%S}.wav"
            audio.write_wav_mono(str(path), pcm)
            print(f"  保存: {path}")
        pipe.run(pcm, f"wakeword:{score:.2f}", t_end)


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
        elif os.environ.get("INPUT", "enter") == "wakeword":
            wakeword_loop(pipe, args.save)
        else:
            mic_loop(pipe, args.save)
    except (KeyboardInterrupt, EOFError):
        print()


if __name__ == "__main__":
    main()
