"""Google Cloud Text-to-Speech（v1 REST）"""
import base64
import os

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
