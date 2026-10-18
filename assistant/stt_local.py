"""ローカル STT（Pi の CPU で動かす）。モデルは scripts/fetch_models.sh で models/ に落とす

- reazon:  ReazonSpeech（k2 zipformer、オフライン transducer）を sherpa-onnx で動かす
- whisper: faster-whisper（CTranslate2）。STT_WHISPER_MODEL で models/ 以下のモデルを選ぶ
どちらも GoogleSTT と同じく transcribe(pcm) で PCM（S16_LE / 16 kHz / mono）を文字列にする。
"""
import os

import numpy as np

from .audio import RATE
from .config import ROOT

MODELS = ROOT / "models"
THREADS = int(os.environ.get("STT_THREADS", "4"))  # Pi 5 のコア数


def to_float32(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768


class ReazonSTT:
    def __init__(self):
        import sherpa_onnx

        d = MODELS / "sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01"
        # STT_REAZON_INT8=0 で量子化前（fp32）のモデルを使う
        suffix = ".int8.onnx" if os.environ.get("STT_REAZON_INT8", "1") == "1" else ".onnx"
        self.model = f"reazon{'-int8' if suffix.startswith('.int8') else ''}"
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(d / f"encoder-epoch-99-avg-1{suffix}"),
            decoder=str(d / f"decoder-epoch-99-avg-1{suffix}"),
            joiner=str(d / f"joiner-epoch-99-avg-1{suffix}"),
            tokens=str(d / "tokens.txt"),
            num_threads=THREADS,
            sample_rate=RATE,
            feature_dim=80,
            decoding_method="greedy_search",
        )

    def transcribe(self, pcm: bytes) -> str:
        stream = self.recognizer.create_stream()
        stream.accept_waveform(RATE, to_float32(pcm))
        self.recognizer.decode_stream(stream)
        return stream.result.text.strip()


class WhisperSTT:
    def __init__(self):
        from faster_whisper import WhisperModel

        self.model = os.environ.get("STT_WHISPER_MODEL", "faster-whisper-small")
        self.beam = int(os.environ.get("STT_WHISPER_BEAM", "1"))
        self.whisper = WhisperModel(str(MODELS / self.model), device="cpu", compute_type="int8",
                                    cpu_threads=THREADS)

    def transcribe(self, pcm: bytes) -> str:
        segments, _ = self.whisper.transcribe(
            to_float32(pcm), language="ja", beam_size=self.beam,
            without_timestamps=True, condition_on_previous_text=False)
        return "".join(s.text for s in segments).strip()
