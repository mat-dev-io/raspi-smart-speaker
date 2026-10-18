# 段階 1: クラウドで一周

Enter キー → 録音 → Google Cloud Speech-to-Text → Claude → Google Cloud Text-to-Speech → 再生。

2026-10-18 実施。Pi 5（段階 0 と同じ構成）。

## 結果

| 完了条件 | 結果 |
|---|---|
| 質問に声で答える | OK（マイクで 9 問。すべて正しく聞き取って答えた） |
| 全区間の遅延の基準値を記録する | 録音終了 → 再生開始の中央値 3.6 秒、p90 4.3 秒（下記） |

## 構成

| 区間 | 使うもの | 既定値（`.env` で変更可） |
|---|---|---|
| 入力 | Enter キー（物理ボタンは後で GPIO に差し替える） | |
| 録音 | `arecord`（2ch で録り ch1 だけ使う） | |
| STT | Google Speech-to-Text v1 `speech:recognize`（同期） | `GOOGLE_STT_MODEL=latest_short` |
| LLM | Claude Messages API。1 問 1 答で履歴なし | `CLAUDE_MODEL=claude-opus-5-5`、`CLAUDE_EFFORT=low` |
| TTS | Google Text-to-Speech v1 `text:synthesize`（LINEAR16 / 16 kHz） | `GOOGLE_TTS_VOICE=ja-JP-Neural2-B` |
| 再生 | `aplay` | |

- Claude には `fallbacks: "default"` を付けている。安全分類器に断られたとき、サーバー側で推奨モデルに切り替えて答え直す（Haiku では付けない）
- 段階 1 ではストリーミングも無音での自動停止もしない。まず素の遅延を基準値として取る

## セットアップ

### API キー

- Google Cloud: プロジェクトで「Cloud Speech-to-Text API」と「Cloud Text-to-Speech API」を有効にし（課金の設定が必要）、API キーを作る。キーの制限で使える API をこの 2 つに絞る
- Anthropic: Console で API キーを作る

### Pi に配置

```sh
./scripts/deploy.sh                                # WSL で実行。rsync で配置し、Pi の .venv に依存を入れる
```

キーは Pi の `.env` にだけ置く（`.env` は deploy でも上書き・削除しない）。

```sh
ssh raspi
cd ~/raspi-smart-speaker && cp .env.example .env && chmod 600 .env && nano .env
```

## 使い方（Pi 上で）

```sh
cd ~/raspi-smart-speaker
.venv/bin/python -m assistant.main                          # Enter で録音開始 → 話す → Enter で終了
.venv/bin/python -m assistant.main --save recordings        # 同じ。録音を WAV で保存する
.venv/bin/python -m assistant.main --wav recordings/*.wav --repeat 3   # 保存した WAV で計測
python3 scripts/latency_summary.py --source wav: --skip-first 1        # 集計
```

各区間の時間は `logs/latency.jsonl` に追記される。文字起こしと回答も入るので、ログはコミットしない（`logs/` は .gitignore 済み）。

## 遅延の測り方

起点は録音終了（2 回目の Enter）、終点は再生開始（`aplay` に音声を渡す直前）。

| 列 | 区間 |
|---|---|
| `stt_ms` | 録音終了 → 文字起こし完了 |
| `llm_ms` | 文字起こし完了 → Claude の回答完了 |
| `tts_ms` | 回答完了 → 音声合成完了 |
| `play_ms` | 音声合成完了 → 再生開始 |
| `total_ms` | 録音終了 → 再生開始（体感の「待ち時間」） |

基準値は、同じ録音（質問 9 個）を `--wav` で 3 周流して取る。1 件目は TLS 接続の確立を含むので `--skip-first 1` で除く。

## 基準値

2026-10-18 計測。マイクで録った質問 9 個（各 2.4〜6.0 秒、中央値 3.1 秒）を `--wav` で 3 周流し、1 件目を除いた 26 件。
設定は既定値（`claude-opus-5-5` / effort `low`、`latest_short`、`ja-JP-Neural2-B`）。

| 区間 | 中央値 | p90 | 最小 | 最大 |
|---|---:|---:|---:|---:|
| STT | 895 | 1117 | 774 | 1375 |
| Claude | 2122 | 2794 | 968 | 3906 |
| TTS | 545 | 666 | 214 | 716 |
| 再生開始 | 1 | 1 | 1 | 1 |
| **合計** | **3562** | **4259** | 2025 | 5034 |

（単位 ms）

- 待ち時間の約 6 割が Claude。回答は中央値 62 文字（14〜97 文字）、読み上げると中央値 11 秒
- Claude の時間は回答の長さとの相関が弱い（相関係数 0.39）。同じ質問でも 2.2 秒から 3.9 秒までばらつく
- TTS の時間は回答の文字数にほぼ比例する（0.84）。全文ができるまで待ってから合成しているため
- STT の時間は録音の長さにほぼ比例する（0.91）。話し終えてから Enter までの無音も送るので、その分遅くなる
- 文字起こしは 3 周とも同じ結果だった（9 問すべて）

### 次の段階で効きそうなこと

基準値から見た候補。効果はこの表と比べて確かめる。

- Claude をストリーミングにし、最初の 1 文ができた時点で TTS → 再生を始める（Claude の残りと TTS が隠れる）
- STT をストリーミング認識にし、話している間に認識を進める
- 無音を検出して録音を自動で止める（Enter が不要になり、末尾の無音も送らない）
- 小さいモデル（`claude-haiku-5-5`）や effort の違いで、速さと回答の質を比べる
