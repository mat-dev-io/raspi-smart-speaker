"""Claude（Messages API）。1 問 1 答で、会話の履歴は持たない"""
import os

import anthropic

SYSTEM = (
    "あなたは日本語の音声アシスタントです。回答はそのまま音声で読み上げられます。"
    "話し言葉で、1〜3 文で簡潔に答えてください。"
    "Markdown、箇条書き、絵文字、URL、記号の羅列は使わないでください。"
)
REFUSAL_REPLY = "すみません、その質問にはお答えできません。"


class Claude:
    def __init__(self):
        self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境変数から読む
        self.model = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
        self.effort = os.environ.get("CLAUDE_EFFORT", "low")

    def ask(self, question: str) -> str:
        kwargs = {}
        if not self.model.startswith("claude-haiku"):
            # 安全分類器に断られたとき、サーバー側で推奨モデルに切り替えて答え直す
            kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM,
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": question}],
            **kwargs,
        )
        if response.stop_reason == "refusal":
            return REFUSAL_REPLY
        return "".join(b.text for b in response.content if b.type == "text").strip()
