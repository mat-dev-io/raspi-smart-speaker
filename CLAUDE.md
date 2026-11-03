# CLAUDE.md

Raspberry Pi 5 で日本語の音声アシスタント（呼びかけ「R2D2」→ STT → LLM → TTS）を作る。

- 構成: 開発は WSL、実行は Pi（`ssh raspi` で配置・実行）。マイクとスピーカーは reSpeaker XVF3800（USB）経由
- 禁止: API キー・IP アドレス・トークン・録音ファイルをコミットしない（`.env` と `*.wav` は .gitignore 済み）
- 音の確認: 音の入出力を変えたら `./scripts/loopback.sh`（WSL で実行）で確かめる。既知の文を流して録り、STT で照合して合否を出す（終了コード 0 = 合格 / 1 = 不合格 / 2 = 環境エラー）
  - 人の耳で確かめる前にこれを使う。仕組みと判定のしきい値は docs/c1-loopback.md
- 常駐: Pi ではアシスタントが systemd のユーザーのサービスで常駐し、マイクを使い続ける。マイクを使う作業の前に `systemctl --user stop assistant`（`loopback.sh` は自動で止めて戻す）。詳しくは docs/stage3-wakeword.md
- スキル: Claude のツール呼び出しで使う道具は `assistant/skills/`（`.env` の `SKILLS` で選ぶ）。スキルや `assistant/llm.py` を変えたら Pi で `scripts/skill_check.py` を流す（0 = 合格 / 1 = 不合格 / 2 = 環境エラー。LIFE は既定で dry-run）。詳しくは docs/stage4-skills.md
- 性能: `assistant/`・`requirements.txt`・`systemd/` を変えたら、コミットの前に `python3 scripts/perf_gate.py`（WSL）で遅延と精度を基準（`bench/baseline.json`）と比べる。`git commit` の直前にフック（`.claude/hooks/perf_gate_hook.sh`）が自動で流し、劣化（終了コード 1）や環境エラー（2）ならコミットを止める。止まったら自分で直そうとせず、表を人に見せて判断を仰ぐ。意図して設定を変えたときだけ `--update-baseline 3` で基準を作り直す。指標としきい値は docs/c3-perf-gate.md。フックは編集と別の Bash コマンドで `git commit` したときだけ正しく判定する（同じコマンドで編集すると編集前を見る）
- 計画: 段階や構成変更のような作業は、実装の前に `plans/<名前>.md` に計画を書き、人の承認（状態を「承認済み」にする）をもらうまでコードを変えない。書式と運用は plans/README.md
