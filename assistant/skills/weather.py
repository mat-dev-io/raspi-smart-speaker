"""天気予報（Open-Meteo。API キー不要）。地点は .env の WEATHER_LAT / WEATHER_LON / WEATHER_PLACE で固定"""
import os

import httpx

from . import Skill

URL = "https://api.open-meteo.com/v1/forecast"
DAYS = {"today": 0, "tomorrow": 1, "day_after_tomorrow": 2}
# WMO の天気コード → 読み上げる言葉
CODES = {0: "快晴", 1: "晴れ", 2: "晴れ時々くもり", 3: "くもり", 45: "霧", 48: "霧",
         51: "霧雨", 53: "霧雨", 55: "霧雨", 56: "着氷性の霧雨", 57: "着氷性の霧雨",
         61: "小雨", 63: "雨", 65: "大雨", 66: "着氷性の雨", 67: "着氷性の雨",
         71: "小雪", 73: "雪", 75: "大雪", 77: "霧雪", 80: "にわか雨", 81: "にわか雨", 82: "激しいにわか雨",
         85: "にわか雪", 86: "激しいにわか雪", 95: "雷雨", 96: "ひょうを伴う雷雨", 99: "ひょうを伴う雷雨"}


def run(args: dict) -> dict:
    lat, lon = os.environ.get("WEATHER_LAT"), os.environ.get("WEATHER_LON")
    if not lat or not lon:
        raise RuntimeError("地点が未設定（.env の WEATHER_LAT / WEATHER_LON）")
    i = DAYS[args["day"]]
    r = httpx.get(URL, timeout=5, params={
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
    r.raise_for_status()
    d = r.json()["daily"]
    code = d["weather_code"][i]
    return {"place": os.environ.get("WEATHER_PLACE", "自宅"), "date": d["time"][i],
            "weather": CODES.get(code, f"コード {code}"),
            "max_c": d["temperature_2m_max"][i], "min_c": d["temperature_2m_min"][i],
            "precipitation_probability_pct": d["precipitation_probability_max"][i]}


SKILL = Skill(
    name="get_weather",
    description="自宅の地点の天気予報（天気・最高と最低気温・降水確率）を返す。今日・明日・あさってのどれか。"
                "天気・気温・雨・傘の質問で使う。地名（place）は読み上げ用なので、返った表記のまま使い、漢字に直さない。",
    input_schema={"type": "object", "properties": {"day": {"type": "string", "enum": list(DAYS)}},
                  "required": ["day"], "additionalProperties": False},
    run=run,
)
