#!/usr/bin/env bash
# 测试-修复循环（非交互）：每轮跑 pytest；全绿退出 0；失败退出 1 并保存失败详情
# 由 agent 驱动：失败 → 修复 → 重跑，直到全绿
# 用法: bash test_loop.sh [轮次标签]

set -u
TAG="${1:-round}"
cd "$(dirname "$0")/backend"

FAIL_LOG="test_loop_failures_${TAG}.txt"
rm -f "$FAIL_LOG"

echo "══════════════════════════════════════════════"
echo " [$TAG] 跑全量测试"
echo "══════════════════════════════════════════════"

timeout 180 python -m pytest tests/ -q --tb=short > "$FAIL_LOG" 2>&1
status=$?

if [ $status -eq 0 ]; then
  echo "🎉 全部测试通过！"
  tail -2 "$FAIL_LOG"
  rm -f "$FAIL_LOG"
  exit 0
fi

echo "❌ 失败（exit=$status），失败用例："
grep -E "^(FAILED|ERROR)" "$FAIL_LOG" | head -30
echo ""
echo "失败详情: backend/$FAIL_LOG"
exit 1
