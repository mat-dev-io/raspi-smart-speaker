#!/usr/bin/env bash
# Claude Code の PreToolUse フック（構成変更 C3）。git commit の直前に性能のゲートを流し、劣化していたらコミットを止める
# 性能に関わるファイル（scripts/perf_gate.py の TARGETS）が前回合格から変わっていなければ、ベンチは流さずに通す
cmd=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')
echo "$cmd" | grep -Eq '(^|[;&|[:space:]])git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit\b' || exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0
log="cache/perf_gate/last.log"
mkdir -p cache/perf_gate
python3 scripts/perf_gate.py --check-only >"$log" 2>&1
rc=$?
[ "$rc" -eq 0 ] && exit 0
{
  echo "性能のゲート（scripts/perf_gate.py）が不合格（終了コード $rc: 1 = 劣化 / 2 = 環境エラー）なので、コミットを止めた。"
  echo "直そうとせず、作業を止めて次の表を人に見せ、どうするか聞くこと（CLAUDE.md）。全文は $log"
  grep -E '^\||^(NG|OK|注意):' "$log"
} >&2
exit 2
