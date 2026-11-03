# 段階 4: スキル機構

Claude のツール呼び出し（Messages API の `tools`）で、答えるだけでなく「調べる・記録する」ができるようにした。
スキルは `assistant/skills/` に 1 ファイル 1 つで置き、`.env` の `SKILLS` で選ぶ。

2026-11-03 実施。実行は Pi 5（段階 3 と同じ構成）。計画は [plans/stage4-skills.md](../plans/stage4-skills.md)。

## 結果

| 完了条件 | 結果 |
|---|---|
| スキルが 3 つ以上あり、Claude が質問に応じて選んで呼ぶ | OK: 3 つ（日時・天気・LIFE）。`scripts/skill_check.py` の 10 問で 10/10 合格（Pi・`claude-opus-5-5`・effort `low`）。声でも 6 回すべて期待どおりのスキルを呼んだ |
| そのうち 1 つは LIFE への記録 | OK: 「LIFE に〜と記録して」で mat-dev-io/LIFE に Issue ができ、「〜を記録しました」と読み上げた（確認で作った #397・#398 は閉じた） |
| スキルを使わない質問の遅延が段階 3 から悪化しない（0.3 秒以内） | OK（中央値）: 録音済みの 9 問を交互に 36 回ずつ流して、合計の中央値 2900 → 2925 ms（+25 ms）。ただし p90 は 3473 → 4076 ms と延びた（下記） |
| スキルを使う質問の遅延を記録する | 声で 6 回: 合計の中央値 5094 / p90 6396 ms。Claude への問い合わせは毎回 2 回、スキルの実行は中央値 886 ms |
| スキルが失敗しても一周が止まらない | OK: 地点の未設定・偽の緯度（HTTP 400）・偽のトークン（HTTP 401）で、それぞれ「調べられませんでした」「記録できませんでした」と答えた |
| 音の入出力に触らない | 触っていない（`loopback.sh` は流していない） |
| 結果を記録し、CLAUDE.md・`.env.example` を直す | この記録。CLAUDE.md にスキルの確認方法、`.env.example` にスキルの設定を足した |

- 声でスキルを使わなかった回は 3 回だけ（うち 1 回は聞き取りの誤り）で比べられなかったので、遅延の比較は録音済みの WAV で取った（下記の「測り方」）。段階 3 の記録（3139 ms）は声で 8 問の値なので、同じ日に同じ WAV で「なし／あり」を比べるほうを判定に使った
- スキルを使わない回の p90 が延びたのは、ツールの定義（3 つ分）と、システムプロンプトに足した文の分だけ入力が増えたことと、Claude の答えのばらつきが混ざったものと思われる。切り分けはしていない
- スキルを使う回は、Claude との往復が 1 回増えるので、使わない回より約 1.5〜2 秒遅い（計画で見込んだ 1〜2 秒の範囲）

## 構成

| スキル（ツール名） | 中身 | 設定（`.env`） |
|---|---|---|
| 日時（`get_datetime`） | 今の日時・曜日・タイムゾーンを返す。ネットワーク不要 | `SKILLS` に `datetime` |
| 天気（`get_weather`） | Open-Meteo（API キー不要）で、今日・明日・あさっての天気・最高と最低気温・降水確率を返す | `WEATHER_LAT` / `WEATHER_LON` / `WEATHER_PLACE`（コミットしない） |
| LIFE（`record_to_life`） | mat-dev-io/LIFE に Issue を作る。タイトルに言ったこと、本文に「音声アシスタント（raspi-smart-speaker）から記録（日時）」。ラベルは付けない | `LIFE_GITHUB_TOKEN`（fine-grained PAT・LIFE だけ・Issues の書き込みだけ・期限 90 日）、`LIFE_DRY_RUN=1` で書かない |

- `assistant/llm.py` は、ツールの呼び出しがあればスキルを実行して `tool_result` を返し、答えが出るまで回す（Claude への問い合わせは最大 3 回）。`SKILLS` が空ならツールを渡さず、システムプロンプトも段階 3 と同じ
- ツールは `strict: true`。スキルの例外は捕まえて `is_error` の結果として Claude に返し、言葉で失敗を伝えさせる。HTTP のエラーは状態コードだけを返す（エラーの文に URL が入り、天気なら緯度経度が journal と Claude に渡るため）
- 安全分類器の fallback（`fallbacks: "default"`）はツールと一緒に使っている。途中で fallback が起きたら、その前の `thinking` と `tool_use` は次の問い合わせに返さない（`echo_content`）。実際に fallback が起きた回はまだない
- `logs/latency.jsonl` には、スキルを有効にしているとき `llm_rounds`（問い合わせ回数）・`skills`（呼んだスキル）・`skill_ms`・`skill_errors` を足す。`llm_ms` は `skill_ms` を含む

### 決めたこと・直したこと

- 地名を Open JTalk が読み違えたので、`WEATHER_PLACE` をひらがなで書いた。Claude が答えるときに漢字へ直さないよう、天気のスキルの説明に「返った表記のまま使う」と書いた（直したあと、答えはひらがなのままになった）
- dry-run のときは、Claude が「試験モードなので保存されていません」と正直に答える。確認用なのでこのままにした

## 測り方

```bash
# スキルの選び方（STT・TTS を通さず文字で 10 問。LIFE は dry-run。0 = 全問合格 / 1 = 不合格 / 2 = 環境エラー）
ssh raspi 'cd raspi-smart-speaker && .venv/bin/python scripts/skill_check.py'
# LIFE に本当に 1 件書く（できた Issue はあとで閉じる）
ssh raspi 'cd raspi-smart-speaker && .venv/bin/python scripts/skill_check.py --real-life --only 6'
# 失敗のさせ方（.env は変えず、その場だけ値を差し替える）
ssh raspi 'cd raspi-smart-speaker && LIFE_GITHUB_TOKEN=invalid .venv/bin/python scripts/skill_check.py --real-life --only 6'
ssh raspi 'cd raspi-smart-speaker && WEATHER_LAT=999 .venv/bin/python scripts/skill_check.py --only 4'

# スキルを使わない回の遅延（段階 1 の録音 9 問を、なし→あり→なし→ありで 2 周ずつ。アシスタントは止めておく）
ssh raspi 'cd raspi-smart-speaker && systemctl --user stop assistant && W=$(cut -f1 recordings/refs.tsv | sed "s|^|recordings/|") &&
  for s in "" "datetime,weather,life" "" "datetime,weather,life"; do SKILLS="$s" .venv/bin/python -m assistant.main --wav $W --repeat 2; done;
  systemctl --user start assistant'
# 声で使った回の集計（--skills used / unused。スキルを有効にしていない行は unused に入らない）
ssh raspi 'cd raspi-smart-speaker && python3 scripts/latency_summary.py --source wakeword --since 2026-11-03T10:50 --skills used'
```

WAV での比較（2026-11-03 10:58〜11:15、各 36 回、単位 ms）:

| 設定 | Claude 中央値 / p90 | 合計 中央値 / p90 |
|---|---:|---:|
| スキルなし（`SKILLS=`） | 2141 / 2774 | 2900 / 3473 |
| スキルあり（3 つ。9 問とも呼ばなかった） | 2250 / 3272 | 2925 / 4076 |

声でスキルを使った回（2026-11-03、6 回、単位 ms）: STT 339・Claude 4345（うちスキルの実行 886）・TTS 264・合計 5094（p90 6396）。

## 次にやること

- スキルを使う回の待ちを縮める: 使う回だけ先に「調べます」と一言読み上げる、または Claude をストリーミングにする（段階 2 から持ち越し）
- スキルを使わない回の p90 が延びた理由を切り分ける（ツールの定義の分か、ばらつきか）。回数を増やして測り直す
- 使っているうちに、Claude が記録を頼まれていないのに記録した回・頼まれたのに記録しなかった回を数える（`logs/latency.jsonl` の `skills` と `transcript`）
- PAT の期限（作成から 90 日）が来る前に作り直す
- タイマー・アラーム（待ち受けと並行して鳴らす仕組みが要る）、会話の履歴（「さっきのを取り消して」）は別の段階で
