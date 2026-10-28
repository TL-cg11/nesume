#!/usr/bin/env bash
# LLM 클라이언트 직접 import 검사. app/app/guardrail/ 밖에서 잡히면 실패한다 (A8 파이프라인만 허용).
# 예외는 scripts/llm-allowlist.txt 에 경로를 한 줄씩 적고 PR 에서 D 리뷰.
set -euo pipefail
cd "$(dirname "$0")/.."

pattern='^[[:space:]]*(from[[:space:]]+[A-Za-z0-9_.]*llm_client|import[[:space:]]+[A-Za-z0-9_.]*llm_client|from[[:space:]]+(anthropic|openai)|import[[:space:]]+(anthropic|openai))\b|bedrock-runtime'
hits=$(grep -rnE "$pattern" app/app --include='*.py' | grep -v '^app/app/guardrail/' || true)

if [ -f scripts/llm-allowlist.txt ]; then
  while IFS= read -r allow; do
    [ -z "$allow" ] && continue
    hits=$(printf '%s\n' "$hits" | grep -v "^$allow" || true)
  done < scripts/llm-allowlist.txt
fi

if [ -n "$hits" ]; then
  echo "LLM direct call outside app/app/guardrail/ (use the A8 pipeline):"
  echo "$hits"
  exit 1
fi
echo "llm import check OK"
