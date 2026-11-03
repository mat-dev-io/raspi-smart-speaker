"""Claude（Messages API）。1 問 1 答で、会話の履歴は持たない

スキル（assistant/skills/）があれば、ツールの呼び出しを実行して結果を返し、答えが出るまで回す（最大 MAX_ROUNDS 往復）。
直近の 1 問の往復回数・呼んだスキル・スキルの時間は self.last に残す（main.py がログに書く）。
"""
import os
import time

import anthropic
import httpx

from . import skills as skills_mod

SYSTEM = (
    "あなたは日本語の音声アシスタントです。回答はそのまま音声で読み上げられます。"
    "話し言葉で、1〜3 文で簡潔に答えてください。"
    "Markdown、箇条書き、絵文字、URL、記号の羅列は使わないでください。"
)
# スキルがあるときだけ足す（スキルなしの呼び出しは段階 3 と同じにする）
SYSTEM_SKILLS = (
    "道具を使えます。今の日時が関わる質問では推測せずに道具で確かめてください。"
    "記録の道具は、利用者がはっきり記録を頼んだときだけ使い、記録したら何を記録したかを短く伝えてください。"
    "道具が失敗したら、できなかったことを短く伝えてください。"
)
REFUSAL_REPLY = "すみません、その質問にはお答えできません。"
GIVE_UP_REPLY = "すみません、うまく処理できませんでした。"
MAX_ROUNDS = 3  # Claude への問い合わせの回数の上限（ツールの結果を返すたびに 1 回増える）


def echo_content(content: list) -> list:
    """次の問い合わせに返す assistant の中身。途中で fallback が起きたら、その前の thinking / tool_use は返さない"""
    last = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
    if last < 0:
        return content
    return [b for b in content[:last] if b.type == "text"] + content[last + 1:]


class Claude:
    def __init__(self, skills: list | None = None):
        self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境変数から読む
        self.model = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
        self.effort = os.environ.get("CLAUDE_EFFORT", "low")
        self.skills = {s.name: s for s in (skills_mod.load() if skills is None else skills)}
        self.last: dict = {}

    def ask(self, question: str) -> str:
        kwargs = {}
        if not self.model.startswith("claude-haiku"):
            # 安全分類器に断られたとき、サーバー側で推奨モデルに切り替えて答え直す
            kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        system = SYSTEM
        if self.skills:
            kwargs["tools"] = [s.tool() for s in self.skills.values()]
            system = SYSTEM + SYSTEM_SKILLS
        messages = [{"role": "user", "content": question}]
        # api_ms は API の呼び出しそのものの時間、input_tokens は送った入力の量（どちらも全往復の合計。C3 の判定に使う）
        self.last = {"rounds": 0, "skills": [], "skill_ms": 0, "skill_errors": 0, "api_ms": 0, "input_tokens": 0}

        for _ in range(MAX_ROUNDS):
            self.last["rounds"] += 1
            t = time.monotonic()
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=2048,
                system=system,
                output_config={"effort": self.effort},
                messages=messages,
                **kwargs,
            )
            self.last["api_ms"] += round((time.monotonic() - t) * 1000)
            self.last["input_tokens"] += response.usage.input_tokens
            if response.stop_reason == "refusal":
                return REFUSAL_REPLY
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            calls = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not calls:
                return text or GIVE_UP_REPLY
            messages.append({"role": "assistant", "content": echo_content(response.content)})
            messages.append({"role": "user", "content": [self._run(c) for c in calls]})
        return GIVE_UP_REPLY

    def _run(self, call) -> dict:
        """スキルを 1 つ実行して tool_result にする。失敗しても止めずに is_error で Claude に返す"""
        self.last["skills"].append(call.name)
        t = time.monotonic()
        try:
            content, is_error = skills_mod.result_text(self.skills[call.name].run(call.input)), False
        except httpx.HTTPStatusError as e:
            # 文に URL（天気なら緯度経度）が入るので、状態コードだけにする
            content, is_error = f"HTTP {e.response.status_code} {e.response.reason_phrase}", True
        except Exception as e:  # noqa: BLE001  スキルの失敗は Claude に言葉で伝えさせる
            content, is_error = f"{type(e).__name__}: {e}", True
        if is_error:
            self.last["skill_errors"] += 1
            print(f"  スキル {call.name} が失敗: {content}")
        self.last["skill_ms"] += round((time.monotonic() - t) * 1000)
        return {"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": is_error}
