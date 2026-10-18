# CLAUDE.md

Raspberry Pi 5 で日本語の音声アシスタント（ボタン → STT → LLM → TTS）を作る。

- 構成: 開発は WSL、実行は Pi（`ssh raspi` で配置・実行）。マイクとスピーカーは reSpeaker XVF3800（USB）経由
- 禁止: API キー・IP アドレス・トークン・録音ファイルをコミットしない（`.env` と `*.wav` は .gitignore 済み）
