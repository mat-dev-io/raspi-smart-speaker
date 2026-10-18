"""XVF3800 の録音・再生。段階 0 と同じく arecord / aplay を使う"""
import array
import io
import os
import signal
import subprocess
import threading
import wave

DEVICE = os.environ.get("XVF_DEVICE", "plughw:Array,0")
RATE = 16000
CHANNELS = 2
VOICE_CHANNEL = 0  # ch1（0 始まり）が音声処理済みの出力


def extract_channel(raw: bytes, channels: int, index: int) -> bytes:
    samples = array.array("h", raw[: len(raw) // (2 * channels) * 2 * channels])
    return samples[index::channels].tobytes()


class Recorder:
    """start() で録音を始め、stop() で ch1 だけの PCM（S16_LE / 16 kHz / mono）を返す"""

    def start(self) -> None:
        self._chunks: list[bytes] = []
        self._proc = subprocess.Popen(
            ["arecord", "-D", DEVICE, "-q", "-t", "raw",
             "-f", "S16_LE", "-r", str(RATE), "-c", str(CHANNELS)],
            stdout=subprocess.PIPE,
        )
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        while chunk := self._proc.stdout.read(4096):
            self._chunks.append(chunk)

    def stop(self) -> bytes:
        self._proc.send_signal(signal.SIGINT)
        self._proc.wait()
        self._reader.join()
        return extract_channel(b"".join(self._chunks), CHANNELS, VOICE_CHANNEL)


def read_wav_mono(path: str) -> bytes:
    """WAV を読み、2ch なら ch1 だけ取り出す。16 kHz / 16bit 以外は受け付けない"""
    with wave.open(path) as w:
        if w.getframerate() != RATE or w.getsampwidth() != 2:
            raise SystemExit(f"NG: {path} は 16 kHz / 16bit ではない")
        raw = w.readframes(w.getnframes())
        ch = w.getnchannels()
    return raw if ch == 1 else extract_channel(raw, ch, VOICE_CHANNEL)


def write_wav_mono(path: str, pcm: bytes) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def wav_seconds(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnframes() / w.getframerate()


def play_wav(wav_bytes: bytes, on_start=None) -> None:
    """WAV を再生し終わるまで待つ。on_start は aplay にデータを渡す直前に呼ぶ（遅延計測用）"""
    proc = subprocess.Popen(["aplay", "-D", DEVICE, "-q", "-"], stdin=subprocess.PIPE)
    if on_start:
        on_start()
    proc.communicate(wav_bytes)
