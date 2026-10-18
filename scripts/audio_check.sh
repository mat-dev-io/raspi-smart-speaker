#!/usr/bin/env bash
# reSpeaker XVF3800 の録音→再生チェック（Pi 上で実行する）
# 使い方: ./audio_check.sh [秒数]   例: ./audio_check.sh 5
set -euo pipefail

SECONDS_TO_RECORD="${1:-5}"
DEVICE="${XVF_DEVICE:-plughw:Array,0}"
RATE="${XVF_RATE:-16000}"
CHANNELS="${XVF_CHANNELS:-2}"
OUT="${XVF_OUT:-/tmp/xvf3800_check.wav}"

echo "== デバイス"
grep -A1 '\[Array ' /proc/asound/cards || { echo "NG: XVF3800 が ALSA に見えない"; exit 1; }

echo "== 録音 ${SECONDS_TO_RECORD} 秒（何か話してください）"
arecord -D "$DEVICE" -f S16_LE -r "$RATE" -c "$CHANNELS" -d "$SECONDS_TO_RECORD" "$OUT"

echo "== レベル"
python3 - "$OUT" <<'EOF'
import array, math, sys, wave
with wave.open(sys.argv[1]) as w:
    ch = w.getnchannels()
    data = array.array("h", w.readframes(w.getnframes()))
for c in range(ch):
    s = data[c::ch]
    peak = max((abs(x) for x in s), default=0)
    rms = math.sqrt(sum(x * x for x in s) / len(s)) if s else 0
    dbfs = 20 * math.log10(rms / 32768) if rms else float("-inf")
    print(f"ch{c + 1}: peak={peak} rms={rms:.0f} ({dbfs:.1f} dBFS)")
total_peak = max((abs(x) for x in data), default=0)
if total_peak < 100:
    print("NG: ほぼ無音")
    sys.exit(2)
print("OK: 音が入っている")
EOF

echo "== 再生（XVF3800 の 3.5mm 端子）"
aplay -D "$DEVICE" "$OUT"
