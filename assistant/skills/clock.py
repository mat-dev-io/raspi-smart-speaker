"""今の日時。Claude は今日の日付を知らないので、日付・曜日・時刻の質問に使う（ネットワーク不要）"""
from datetime import datetime

from . import Skill

WEEKDAYS = "月火水木金土日"


def run(_: dict) -> dict:
    now = datetime.now().astimezone()
    return {"datetime": now.isoformat(timespec="minutes"),
            "weekday": WEEKDAYS[now.weekday()] + "曜日",
            "timezone": now.tzname()}


SKILL = Skill(
    name="get_datetime",
    description="今の日付・曜日・時刻を返す。今日・明日・何曜日・何時など、今の日時が関わる質問では必ず使う。",
    input_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    run=run,
)
