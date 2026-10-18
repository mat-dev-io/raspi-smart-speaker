"""Google Cloud Speech-to-Text（v1 REST, 同期認識）"""
import base64
import os

import httpx

from .audio import RATE
from .config import require

URL = "https://speech.googleapis.com/v1/speech:recognize"


class GoogleSTT:
    def __init__(self, http: httpx.Client):
        self.http = http
        self.key = require("GOOGLE_API_KEY")
        self.model = os.environ.get("GOOGLE_STT_MODEL", "latest_short")

    def transcribe(self, pcm: bytes) -> str:
        body = {
            "config": {
                "encoding": "LINEAR16",
                "sampleRateHertz": RATE,
                "languageCode": "ja-JP",
                "model": self.model,
                "enableAutomaticPunctuation": True,
            },
            "audio": {"content": base64.b64encode(pcm).decode()},
        }
        r = self.http.post(URL, json=body, headers={"X-Goog-Api-Key": self.key})
        if r.is_error:
            raise RuntimeError(f"STT {r.status_code}: {r.text}")
        results = r.json().get("results", [])
        return "".join(res["alternatives"][0]["transcript"] for res in results if res.get("alternatives"))
