# 段階 2: ローカルへ置き換え

STT・TTS を 1 段ずつ Pi の上で動くものに替え、段階 1 のクラウド版と比べる。

2026-10-18 実施。Pi 5（8GB、Ubuntu 24.04、Python 3.12）。段階 1 と同じ構成。

## 結果

| 完了条件 | 結果 |
|---|---|
| 段ごとの遅延・精度の比較表 | OK（STT・TTS とも下記） |

### 比較表

| 段 | 版 | 遅延 中央値 / p90 | 精度 | 一周の合計 中央値 / p90 |
|---|---|---:|---|---:|
| STT | クラウド（Google `latest_short`） | 902 / 1112 ms | CER 1.0%（1/102） | 3562 / 4259 ms |
| STT | **ローカル（ReazonSpeech int8）** | **276 / 386 ms** | CER 4.9%（5/102）。回答は 9 問とも正しかった | **3068 / 3471 ms** |
| TTS | クラウド（Google `ja-JP-Neural2-B`）、全文をまとめて | 555 / 621 ms | かな CER 2.6%（19/723） | 3068 / 3471 ms |
| TTS | クラウド（同）、1 文ずつ | 396 / 460 ms | 同上 | 2991 / 3392 ms |
| TTS | **ローカル（Open JTalk `mei`）、1 文ずつ** | **362 / 596 ms** | かな CER 2.9%（21/723）。ループバックテスト 5/5 | **2962 / 3764 ms** |

- STT は ReazonSpeech に替えた（Pi の `.env` を `STT_ENGINE=reazon` にした。`google` の行もコメントで残してあり、入れ替えれば戻る）。STT の待ちが 約 0.6 秒縮み、一周の合計は中央値で 0.5 秒、p90 で 0.8 秒縮んだ
- 文字誤りは増えた（1% → 5%）が、誤りは文末の「は」の抜けと、もともと声が小さかった 1 問に集まっている。Claude は誤った 3 問にも正しく答えた
- 一周の合計の差には Claude のばらつきも入っている（Claude の中央値は段階 1 で 2122 ms、今回 2288 ms）。STT の差だけ見るなら下の単体の表を使う
- TTS の行の一周の合計は、どれも STT をローカル（ReazonSpeech int8）にしたもの。「全文をまとめて」の行は STT の段で測った値（TTS は段階 1 と同じ作り。段階 1 の TTS 単独の値は 545 / 666 ms）
- TTS は Open JTalk（声 `mei`）なら Pi の上で間に合う。回答を 1 文ずつ合成すれば、待ち時間（1 文目ができるまで）はクラウドとほぼ同じで、一周の合計の中央値も変わらない。p90 は 0.37 秒悪い（TTS で 0.14 秒、Claude のばらつきで 0.22 秒）
- 1 文ずつ合成する作りはクラウドにも効く。全文を待つより TTS の待ちが中央値・p90 とも 0.16 秒縮む
- VOICEVOX は Pi 5 の CPU では遅すぎて使えない（1 文目だけで中央値 6.9 秒）
- Pi の `.env` の TTS はまだ `google` のまま。声の自然さは耳で聞いてから決める（下記「聞き比べ」）

## STT

### 候補と単体の比較

段階 1 で録った質問 9 本（各 2.4〜6.0 秒）を 3 周、STT だけに通した。1 件目は暖機（クラウドは TLS 接続の確立）を含むので除いた 26 件。
CER（文字誤り率）は 1 周目の 9 本で数えた（3 周とも同じ文字起こしになる）。

| 版 | 中央値 | p90 | 最小〜最大 | RTF | CER | 読み込み | メモリ |
|---|---:|---:|---:|---:|---:|---:|---:|
| Google `latest_short`（クラウド） | 902 | 1112 | 745〜1496 | 0.29 | 1.0% | — | 44 MB |
| **ReazonSpeech int8**（sherpa-onnx） | **276** | **386** | 190〜509 | 0.09 | 4.9% | 3.3 s | 397 MB |
| ReazonSpeech fp32 | 552 | 768 | 403〜1159 | 0.17 | 4.9% | 4.2 s | 929 MB |
| faster-whisper `small`（int8、beam 1） | 6473 | 7116 | 5630〜7456 | 2.03 | 12.7% | 1.9 s | 645 MB |
| kotoba-whisper v2.0（int8、beam 1） | 31112 | 31570 | 28777〜32394 | 9.78 | 3.9% | 5.3 s | 1543 MB |

（遅延の単位 ms。RTF = 処理時間 / 録音の長さ。メモリはプロセスの最大 RSS。どれも 4 スレッド）

- ReazonSpeech は int8 でも fp32 と同じ文字起こしになり、速さは 2 倍・メモリは半分以下。int8 を使う
- Whisper 系は短い質問でも入力を 30 秒に詰め物して encoder に通すので、Pi の CPU では録音の長さによらず遅い。kotoba-whisper は精度は一番良いが 30 秒かかり使えない
- ReazonSpeech で、末尾に無音 0.5 秒を足す・`modified_beam_search` にする・音量をそろえる（RMS -20 / -14 dBFS）も試したが、文字起こしは変わらなかった

### 文字起こしの違い

| 正解 | Google | ReazonSpeech | whisper small | kotoba-whisper |
|---|---|---|---|---|
| 日本で一番長い川は | 同じ | 日本で一番長い川 | 同じ | 同じ |
| 1年で一番昼が長い日はいつ | 同じ | 同じ（一年） | 1年で一番昼がなかった時はいつ? | 同じ |
| ペンギンは空を飛べる | 同じ | ペンギンは空をという | ヘンギンは空を取るよ | ペンギンは空を取るよ |
| 123かける4は | 123かける4= | 百二十三×四は | 123×4 | 123×4は |
| 地球から月までの距離は | 同じ | 地球から月までの距離を | 地球から突きまでの距離を | 地球から月までの距離を |

ほかの 4 問はすべての版で正しかった。「ペンギン」の録音は全体に声が小さく（-19〜-37 dBFS）、ローカルの 3 つがすべて「飛べる」を聞き違えた。

### 正解文と CER の数え方

- 正解文は段階 1 の Google の文字起こし（9 問すべて正しく聞き取れていた）から句読点を除いたもの。「123かける4=」だけは話した本人に確かめて「123かける4は」にした。Pi の `recordings/refs.tsv` に置く（録音と同じ場所。コミットしない）
- 句読点・記号・空白は除き、全角/半角をそろえてから編集距離を数える（ループバックテストの照合と同じ `normalize`）
- 読みが同じ表記の違いは正解の候補として並べる（「1年 / 一年」「どれくらい / どれぐらい」「123かける4 / 百二十三×四」）。誤りは最も近い候補で数え、文字数は最初の候補で数える
- 質問が 9 問しかないので、CER の差は大まかな目安。1 文字の差で 1% 変わる

## 使い方

### セットアップ（Pi で 1 回だけ）

```sh
./scripts/deploy.sh                       # WSL で実行。requirements.txt に sherpa-onnx と faster-whisper を足した
ssh raspi
cd ~/raspi-smart-speaker && ./scripts/fetch_models.sh   # models/ に約 2.7 GB（ReazonSpeech 741 MB、Whisper 2 種）
```

`models/` は .gitignore 済みで、`deploy.sh` でも消さない。ReazonSpeech だけ使うなら Whisper の 2 つは要らない（`fetch_models.sh` の for 文を外す）。

### 切り替え

`.env` に書く（既定は `STT_ENGINE=google` で、段階 1 と同じ動き）。

```sh
STT_ENGINE=reazon                 # google / reazon / whisper
STT_REAZON_INT8=1                 # 0 で fp32
STT_WHISPER_MODEL=faster-whisper-small    # または kotoba-whisper-v2.0-faster
```

ローカルの STT は起動時にモデルを読み込む（ReazonSpeech int8 で 約 3 秒）。1 回目の認識は暖機で 約 0.5 秒かかり、2 回目から 0.2〜0.4 秒。

ループバックテストの照合は今も Google STT を使う（`assistant/loopback.py`）。STT の切り替えの影響は受けない。

### 計測

```sh
STT_ENGINE=reazon .venv/bin/python scripts/stt_bench.py --refs recordings/refs.tsv --repeat 3   # STT 単体
STT_ENGINE=reazon .venv/bin/python -m assistant.main --wav $(cut -f1 recordings/refs.tsv | sed 's|^|recordings/|') --repeat 3
python3 scripts/latency_summary.py --source wav: --since 2026-10-18T19:58 --skip-first 1          # 一周の集計（--since は計測を始めた時刻）
```

STT 単体の結果は `logs/stt_bench.jsonl` に追記される（文字起こしも入るのでコミットしない）。

## TTS

### 候補と単体の比較

段階 1 で 9 問に返ってきた回答（各 15〜95 文字、中央値 62 文字）を 3 周、TTS だけに通した。1 件目は暖機（クラウドは TLS 接続の確立）を含むので除いた 26 件。
精度は 1 周目の合成音を Google STT（`latest_long`）に通し、元の回答と比べた（9 本、正解 519 文字・読み 723 文字）。

| 版 | 全文 中央値 / p90 | 1 文目 中央値 / p90 | RTF | 途中の無音 | CER | かな CER | 読み込み | メモリ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Google `ja-JP-Neural2-B`（クラウド） | 256 / 655 | 212 / 376 | 0.02 | 0 | 8.1% | 2.6% | — | 233 MB |
| **Open JTalk `mei`**（pyopenjtalk-plus） | **799 / 1232** | **394 / 501** | 0.07 | 0 | 6.9% | 2.9% | 0.2 s | 322 MB |
| Open JTalk `takumi`（男声） | 1057 / 1863 | 500 / 765 | 0.09 | 0 | 6.6% | 2.1% | 0.2 s | 366 MB |
| VOICEVOX core 0.17（ずんだもん ノーマル） | 13988 / 20063 | 6925 / 8685 | 1.18 | 中央値 214・最大 6967 | 8.5% | 2.9% | 1.6 s | 1478 MB |

（遅延の単位 ms。RTF = 全文の合成時間 / 音声の長さ。途中の無音 = 1 文ずつ合成しながら再生したとき、次の文が間に合わずに空く時間の合計。メモリはプロセスの最大 RSS。ローカルはどれも 4 スレッド）

- Open JTalk は 1 文目が 0.4 秒でできる。2 文目以降は再生している間に間に合い、途中で途切れない
- VOICEVOX は合成が再生より遅い（RTF 1.2）。1 文ずつにしても 1 文目に 7 秒かかり、途中でも最大 7 秒止まる。旧形式のモデル（0.16.4）・2 スレッドも試したが、速くはならなかった（44 文字で 9〜15 秒）。合成中は Pi が 88 °C まで上がり、クロックが抑えられた（`vcgencmd get_throttled` = `0xe0006`）
- クラウドの「全文」の中央値（256 ms）は一周の中で測った値（555 ms）より小さい。このベンチは要求を続けて送るので、Claude を待つ間に接続が空かないためと思われる。一周の比較には上の比較表（`main.py --wav` で測った値）を使う
- 候補外: Piper には日本語の声がない。sherpa-onnx の配布モデル（`tts-models`）にも日本語用のものは見当たらなかった（Kokoro の多言語版は試していない）

### 精度の数え方

- 合成音を STT に通して元の文と比べるので、STT の誤りも入る。9 本のうち 7 本は、クラウドと `mei` の文字起こしが一字一句同じだった
- 文字の CER は表記の違いが大半を占める。STT は「キロメートル」を「km」、「三百六十七」を「36。7」と書くので、どの声でも同じように誤りに数えられる。そこで両方を Open JTalk の読み（カタカナ）に直して比べた値（かな CER）を主に見る
- 読みに直すのも Open JTalk なので、読みの推定の誤りは打ち消し合う。目安として使う

### ループバックテスト

`./scripts/loopback.sh --tts openjtalk` で、Open JTalk の音をスピーカー → マイクに通した。5/5 文が合格したが、余裕は少ない。

| | 一致度 | SNR | 相関 | 途切れ |
|---|---|---|---|---|
| Google（既定） | 5 文とも 1.00 | 16.3〜19.3 dB | 0.87〜0.89 | 10〜20 ms |
| Open JTalk `mei` | 0.90〜1.00（1 文は STT が空を返し、流し直しで合格） | 15.5〜19.4 dB | 0.91〜0.96 | 0〜10 ms |

音の信号（SNR・相関・途切れ）は Google と同じかそれより良い。落ちたのは文字起こしで、「今日は → 今日の」「起きて犬と → 起きていると」と聞き違えた。

### 聞き比べ

自然さは数字では測れないので耳で決める。ベンチの 1 周目の合成音を Pi の `recordings/tts/` に残してある（`<声>-<番号>.wav`、番号は `recordings/tts_texts.txt` の行。コミットしない）。

```sh
ssh raspi 'cd raspi-smart-speaker && for v in ja-JP-Neural2-B openjtalk-mei openjtalk-takumi voicevox-3; do echo $v; aplay -q -D plughw:Array,0 recordings/tts/$v-3.wav; done'
```

### 1 文ずつ合成して再生する

`assistant/main.py` は回答を句点・感嘆符・疑問符・改行で文に分け（`tts.split_sentences`）、1 文目ができたら再生を始める。2 文目以降は再生している間に合成し、同じ `aplay` に続けて渡す（`audio.Player`）。

- `tts_ms` の意味が段階 1 から変わった: 回答完了 → **1 文目の**合成完了。段階 1 と同じ全文の時間は `tts_all_ms`、次の文が間に合わず空いた時間は `stall_ms` に入る
- `TTS_SPLIT=0` で段階 1 と同じく全文をまとめて合成する
- 回答は 1〜4 文（中央値 2 文）なので、1 文目は回答の半分ほどになる

### 使い方

セットアップ（Pi で 1 回だけ）。`./scripts/deploy.sh` で `pyopenjtalk-plus` と `voicevox_core` が入る。

```sh
ssh raspi
cd ~/raspi-smart-speaker && ./scripts/fetch_models.sh   # VOICEVOX（184 MB）と takumi の声（3 MB）を足した
```

- VOICEVOX のダウンローダーは利用規約を表示して同意を求める（y で同意）。使わないなら `fetch_models.sh` の VOICEVOX の段を外す
- `mei` の声は pyopenjtalk-plus に同梱されている（名古屋工業大学 MMDAgent、CC BY 3.0）。`takumi` は MMDAgent の example から取り出す（規約は `models/htsvoice/COPYRIGHT-takumi.txt`）
- VOICEVOX の音声を使うときは「VOICEVOX:ずんだもん」のようにクレジットを書く（声ごとの規約は `models/voicevox/models/README.txt`）

`.env` で切り替える（既定は `TTS_ENGINE=google`）。

```sh
TTS_ENGINE=openjtalk              # google / openjtalk / voicevox
TTS_OPENJTALK_VOICE=mei           # mei（女声）/ takumi（男声）
TTS_OPENJTALK_SPEED=1.0
TTS_VOICEVOX_STYLE=3              # 3 = ずんだもん（ノーマル）。0.vvm のスタイル ID
TTS_SPLIT=1                       # 0 で全文をまとめて合成する
```

ローカルの TTS は 16 kHz に変換して返す（Open JTalk は 48 kHz、VOICEVOX は 24 kHz で合成する）。

### 計測

```sh
.venv/bin/python - <<'PY'   # recordings/tts_texts.txt を作る（段階 1 の計測で 9 問それぞれに最初に返った回答）
import json
seen = {}
for line in open("logs/latency.jsonl"):
    r = json.loads(line)
    if r.get("source", "").startswith("wav:") and r.get("reply"):
        seen.setdefault(r["source"], r["reply"].replace("\n", ""))
open("recordings/tts_texts.txt", "w").write("\n".join(seen.values()) + "\n")
PY
TTS_ENGINE=openjtalk .venv/bin/python scripts/tts_bench.py --texts recordings/tts_texts.txt --repeat 3 --keep recordings/tts   # TTS 単体
TTS_ENGINE=openjtalk .venv/bin/python -m assistant.main --wav $(cut -f1 recordings/refs.tsv | sed 's|^|recordings/|') --repeat 3
python3 scripts/latency_summary.py --source wav: --since 2026-10-18T21:20 --skip-first 1     # 一周の集計（全文の合成・途中の無音の行も出る）
```

TTS 単体の結果は `logs/tts_bench.jsonl` に追記される（回答の文も入るのでコミットしない）。比較表の一周の値は 2026-10-18 21:13（クラウド）と 21:20（Open JTalk）から測った各 26 件。

## 次にやること

- 声を決める（`mei` / `takumi` / クラウド）。Open JTalk にするなら Pi の `.env` を `TTS_ENGINE=openjtalk` にする
- Pi 5 の冷却を見直す。VOICEVOX を回すと 88 °C で抑制がかかり、ほかの計測を続けたときも 65〜70 °C あった
- Claude をストリーミングにして、1 文目ができた時点で TTS に回す（いまは Claude の全文を待っている。待ち時間の 8 割が Claude）
