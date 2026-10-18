"""Google Cloud Text-to-Speech（v1 REST）と、TTS の選択"""
import base64
import os
import re

import httpx

from .audio import RATE
from .config import require

URL = "https://texttospeech.googleapis.com/v1/text:synthesize"


class GoogleTTS:
    def __init__(self, http: httpx.Client):
        self.http = http
        self.key = require("GOOGLE_API_KEY")
        self.voice = os.environ.get("GOOGLE_TTS_VOICE", "ja-JP-Neural2-B")

    def synthesize(self, text: str) -> bytes:
        """WAV（ヘッダー付き LINEAR16 / 16 kHz / mono）を返す"""
        body = {
            "input": {"text": text},
            "voice": {"languageCode": "ja-JP", "name": self.voice},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": RATE},
        }
        r = self.http.post(URL, json=body, headers={"X-Goog-Api-Key": self.key})
        if r.is_error:
            raise RuntimeError(f"TTS {r.status_code}: {r.text}")
        return base64.b64decode(r.json()["audioContent"])


def split_sentences(text: str) -> list[str]:
    """句点・感嘆符・疑問符・改行で文に分ける（区切りの記号は前の文に残す）"""
    return [s.strip() for s in re.split(r"(?<=[。！？!?])|\n", text) if s.strip()]


def make_tts(http: httpx.Client):
    """TTS_ENGINE（google / openjtalk / voicevox）で TTS を選ぶ。ローカル版は使うときだけ読み込む"""
    engine = os.environ.get("TTS_ENGINE", "google")
    if engine == "google":
        return GoogleTTS(http)
    from . import tts_local
    if engine == "openjtalk":
        return tts_local.OpenJTalkTTS()
    if engine == "voicevox":
        return tts_local.VoicevoxTTS()
    raise SystemExit(f"NG: TTS_ENGINE={engine} は未対応（google / openjtalk / voicevox）")
