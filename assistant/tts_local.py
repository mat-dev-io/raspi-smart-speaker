"""ローカル TTS（Pi の CPU で動かす）。モデルと声は scripts/fetch_models.sh で models/ に落とす

- openjtalk: Open JTalk（HMM）を pyopenjtalk-plus で動かす。声は TTS_OPENJTALK_VOICE で選ぶ
- voicevox:  VOICEVOX core（ONNX）。声は TTS_VOICEVOX_STYLE（スタイル ID）で選ぶ
どちらも GoogleTTS と同じく synthesize(text) で WAV（LINEAR16 / 16 kHz / mono）を返す。
"""
import io
import os
import wave

import numpy as np

from .audio import RATE
from .stt_local import MODELS, THREADS

# Open JTalk の声。mei は pyopenjtalk-plus に同梱、takumi は MMDAgent の example から取り出したもの
TAKUMI = MODELS / "htsvoice" / "takumi_normal.htsvoice"
VOICEVOX = MODELS / "voicevox"
VOICEVOX_ORT = VOICEVOX / "onnxruntime" / "lib" / "libvoicevox_onnxruntime.so.1.23.2"
VOICEVOX_DICT = VOICEVOX / "dict" / "open_jtalk_dic_utf_8-1.11"
VOICEVOX_VVM = VOICEVOX / "models" / "vvms" / "0.vvm"  # 四国めたん・ずんだもん・春日部つむぎ・雨晴はう


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    """周波数領域で切り詰めて dst Hz にする（dst の半分より上は落ちる）"""
    if src == dst:
        return x
    n = round(len(x) * dst / src)
    spec = np.fft.rfft(x)[: n // 2 + 1]
    return np.fft.irfft(spec, n) * n / len(x)


def to_wav(x: np.ndarray, rate: int) -> bytes:
    """int16 の値域の配列を 16 kHz の WAV にする"""
    pcm = np.clip(resample(x.astype(np.float64), rate, RATE), -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class OpenJTalkTTS:
    def __init__(self):
        import pyopenjtalk

        self.pyopenjtalk = pyopenjtalk
        name = os.environ.get("TTS_OPENJTALK_VOICE", "mei")  # mei（女声）/ takumi（男声）
        paths = {"mei": pyopenjtalk.DEFAULT_HTS_VOICE, "takumi": str(TAKUMI).encode()}
        if name not in paths:
            raise SystemExit(f"NG: TTS_OPENJTALK_VOICE={name} は未対応（mei / takumi）")
        self.voice = f"openjtalk-{name}"
        self.engine = pyopenjtalk.HTSEngine(paths[name])
        self.speed = float(os.environ.get("TTS_OPENJTALK_SPEED", "1.0"))

    def synthesize(self, text: str) -> bytes:
        labels = self.pyopenjtalk.extract_fullcontext(text)
        self.engine.set_speed(self.speed)  # synthesize() のたびに戻るので毎回設定する
        x = self.engine.synthesize(labels)
        return to_wav(x, self.engine.get_sampling_frequency())  # 48 kHz


class VoicevoxTTS:
    def __init__(self):
        from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer, VoiceModelFile

        self.style = int(os.environ.get("TTS_VOICEVOX_STYLE", "3"))  # 3 = ずんだもん（ノーマル）
        self.voice = f"voicevox-{self.style}"
        ort = Onnxruntime.load_once(filename=str(VOICEVOX_ORT))
        self.synth = Synthesizer(ort, OpenJtalk(str(VOICEVOX_DICT)), cpu_num_threads=THREADS)
        with VoiceModelFile.open(str(VOICEVOX_VVM)) as model:
            self.synth.load_voice_model(model)

    def synthesize(self, text: str) -> bytes:
        # 出力は 24 kHz の倍数しか選べないので、24 kHz で合成してから 16 kHz に落とす
        with wave.open(io.BytesIO(self.synth.tts(text, self.style))) as w:
            rate = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), np.int16)
        return to_wav(x, rate)
