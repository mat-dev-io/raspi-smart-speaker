# 段階 2: ローカルへ置き換え

STT・TTS を 1 段ずつ Pi の上で動くものに替え、段階 1 のクラウド版と比べる。

2026-10-18 実施。Pi 5（8GB、Ubuntu 24.04、Python 3.12）。段階 1 と同じ構成。

## 結果

| 完了条件 | 結果 |
|---|---|
| 段ごとの遅延・精度の比較表 | STT: 済み（下記）。TTS: これから |

### 比較表

| 段 | 版 | 遅延 中央値 / p90 | 精度 | 一周の合計 中央値 / p90 |
|---|---|---:|---|---:|
| STT | クラウド（Google `latest_short`） | 902 / 1112 ms | CER 1.0%（1/102） | 3562 / 4259 ms |
| STT | **ローカル（ReazonSpeech int8）** | **276 / 386 ms** | CER 4.9%（5/102）。回答は 9 問とも正しかった | **3068 / 3471 ms** |
| TTS | クラウド（Google `ja-JP-Neural2-B`） | 545 / 666 ms | | |
| TTS | ローカル | | | |

- STT は ReazonSpeech に替えた（Pi の `.env` を `STT_ENGINE=reazon` にした。`google` の行もコメントで残してあり、入れ替えれば戻る）。STT の待ちが 約 0.6 秒縮み、一周の合計は中央値で 0.5 秒、p90 で 0.8 秒縮んだ
- 文字誤りは増えた（1% → 5%）が、誤りは文末の「は」の抜けと、もともと声が小さかった 1 問に集まっている。Claude は誤った 3 問にも正しく答えた
- 一周の合計の差には Claude のばらつきも入っている（Claude の中央値は段階 1 で 2122 ms、今回 2288 ms）。STT の差だけ見るなら下の単体の表を使う

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

## 次: TTS

- 候補: VOICEVOX core（品質が良い。Pi の CPU で長い文が間に合うか）、Open JTalk（速いが機械的）、Piper（日本語の声が少ない）
- 精度は「合成した音を Google STT に通して元の文と照合する」一致度で測れる（ループバックテストと同じ照合）。自然さは耳で聞いて決める
- 回答は中央値 62 文字。全文を待ってから合成すると、ローカル TTS は文字数に比例して遅くなりやすい。1 文ずつ合成して再生を始める作りと合わせて比べる
