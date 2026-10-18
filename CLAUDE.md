# CLAUDE.md

Raspberry Pi 5 で日本語の音声アシスタント（ボタン → STT → LLM → TTS）を作る。

- 構成: 開発は WSL、実行は Pi（`ssh raspi` で配置・実行）。マイクとスピーカーは reSpeaker XVF3800（USB）経由
- 禁止: API キー・IP アドレス・トークン・録音ファイルをコミットしない（`.env` と `*.wav` は .gitignore 済み）
- 音の確認: 音の入出力を変えたら `./scripts/loopback.sh`（WSL で実行）で確かめる。既知の文を流して録り、STT で照合して合否を出す（終了コード 0 = 合格 / 1 = 不合格 / 2 = 環境エラー）
  - 人の耳で確かめる前にこれを使う。仕組みと判定のしきい値は docs/c1-loopback.md
