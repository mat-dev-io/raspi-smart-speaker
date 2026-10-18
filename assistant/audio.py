"""XVF3800 の録音・再生。段階 0 と同じく arecord / aplay を使う"""
import array
import io
import os
import queue
import signal
import subprocess
import threading
import wave

DEVICE = os.environ.get("XVF_DEVICE", "plughw:Array,0")
RATE = 16000
CHANNELS = 2
VOICE_CHANNEL = 0  # ch1（0 始まり）が音声処理済みの出力
LOOPBACK_CHANNEL = 1  # ch2 は自分の再生音がエコーキャンセルで消されずに残る（ループバックテスト用）


def extract_channel(raw: bytes, channels: int, index: int) -> bytes:
    samples = array.array("h", raw[: len(raw) // (2 * channels) * 2 * channels])
    return samples[index::channels].tobytes()


class Recorder:
    """start() で録音を始め、stop() で 1ch 分（既定は ch1）の PCM（S16_LE / 16 kHz / mono）を返す"""

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

    def stop(self, channel: int = VOICE_CHANNEL) -> bytes:
        return self.stop_all()[channel]

    def stop_all(self) -> list[bytes]:
        """全チャンネルをそれぞれ mono の PCM で返す"""
        self._proc.send_signal(signal.SIGINT)
        self._proc.wait()
        self._reader.join()
        raw = b"".join(self._chunks)
        return [extract_channel(raw, CHANNELS, c) for c in range(CHANNELS)]


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


def wav_pcm(wav_bytes: bytes) -> bytes:
    """WAV のヘッダーを除いた PCM"""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.readframes(w.getnframes())


def play_wav(wav_bytes: bytes, on_start=None) -> None:
    """WAV を再生し終わるまで待つ。on_start は aplay にデータを渡す直前に呼ぶ（遅延計測用）"""
    proc = subprocess.Popen(["aplay", "-D", DEVICE, "-q", "-"], stdin=subprocess.PIPE)
    if on_start:
        on_start()
    proc.communicate(wav_bytes)
    if proc.returncode:
        raise RuntimeError(f"再生できなかった（aplay の終了コード {proc.returncode}）")


class Player:
    """PCM（S16_LE / 16 kHz / mono）を少しずつ渡して続けて再生する。1 文ずつ合成した音を途切れなくつなぐ用

    aplay への書き込みは別スレッドで行う（パイプが詰まっても、呼び出し側は次の文の合成を続けられる）。
    渡すのが再生に追いつかなければ、その間は無音になる。
    """

    def __init__(self):
        self._proc = subprocess.Popen(
            ["aplay", "-D", DEVICE, "-q", "-t", "raw", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-"],
            stdin=subprocess.PIPE,
        )
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._writer = threading.Thread(target=self._write, daemon=True)
        self._writer.start()

    def _write(self) -> None:
        while (pcm := self._queue.get()) is not None:
            self._proc.stdin.write(pcm)
        self._proc.stdin.close()

    def write(self, pcm: bytes) -> None:
        self._queue.put(pcm)

    def close(self) -> None:
        """渡した音を再生し終わるまで待つ"""
        self._queue.put(None)
        self._writer.join()
        self._proc.wait()
        if self._proc.returncode:
            raise RuntimeError(f"再生できなかった（aplay の終了コード {self._proc.returncode}）")
