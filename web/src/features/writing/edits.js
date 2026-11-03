// 맞춤법 검사 결과(A7 제안)를 목록 모양으로 바꾸고, 고른 것만 글에 반영한다.
//
// 서버 /writing/apply 와 같은 두 가지를 화면에서 지킨다.
//   - 위치의 글이 제안을 받을 때와 같은지 본다 (서버 409 와 같은 판단)
//   - 겹치는 제안은 함께 고를 수 없다

// 이보다 짧은 조각("는" → "은")은 어디인지 알 수 없어 앞뒤 글을 붙여 보여준다
const SHORT = 8
const CONTEXT = 10

function withContext(text, e) {
  if (e.original.length >= SHORT) return e
  return {
    ...e,
    before: text.slice(Math.max(0, e.start - CONTEXT), e.start),
    after: text.slice(e.end, e.end + CONTEXT),
  }
}

// 서버 응답 → { id, start, end, original, replacement, reason, tags, before?, after? }
export function toEdits(text, proofread) {
  return proofread.suggestions
    .filter((s) => s.is_replacement)
    .map((s) =>
      withContext(text, {
        id: s.id,
        start: s.start,
        end: s.end,
        original: s.original,
        replacement: s.suggested,
        reason: s.reason,
        tags: [
          s.source === 'llm' ? { label: 'AI 제안', tone: 'llm' } : { label: '맞춤법' },
          // 모델 제안은 근거를 댈 수 없다. 규칙 제안과 같은 무게로 보이면 구분 없이 수락하게 된다
          ...(s.confidence === 'medium' ? [{ label: '확인 필요', tone: 'check' }] : []),
        ],
      }),
    )
    .sort((a, b) => a.start - b.start || a.end - b.end)
}

// 원문 → 제안을 낱말 단위로 비교한다. 바뀐 낱말만 표시하려고 쓴다
// (문장 통째로 빨간 줄을 그으면 어디가 바뀌었는지 사용자가 다시 찾아야 한다).
//
// 낱말 = 공백이 아닌 덩어리. 공백도 조각으로 남겨 이어 붙이면 원문이 그대로 나온다.
// 띄어쓰기만 바뀐 경우("진행 했습니다" → "진행했습니다")도 낱말이 달라져 잡힌다.
const TOKEN = /\s+|[^\s]+/g

export function diffWords(before, after) {
  const a = before.match(TOKEN) ?? []
  const b = after.match(TOKEN) ?? []
  // LCS 표. 제안은 한두 문장이라 낱말 수가 작다
  const dp = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const out = []
  const push = (op, text) => {
    const last = out[out.length - 1]
    if (last && last.op === op) last.text += text
    else out.push({ op, text })
  }
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push('equal', a[i])
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) push('del', a[i++])
    else push('ins', b[j++])
  }
  while (i < a.length) push('del', a[i++])
  while (j < b.length) push('ins', b[j++])
  return out
}

export const overlaps = (a, b) => a.start < b.end && b.start < a.end

// 겹치지 않게 앞에서부터 고른다 ("모두 선택")
export function pickNonOverlapping(edits) {
  const picked = []
  for (const e of edits) {
    if (!picked.some((p) => overlaps(p, e))) picked.push(e)
  }
  return new Set(picked.map((e) => e.id))
}

export class StaleEdit extends Error {}

// 뒤에서부터 바꾼다. 앞을 먼저 바꾸면 뒤 제안의 위치가 밀린다
export function applyEdits(text, edits) {
  const sorted = [...edits].sort((a, b) => b.start - a.start)
  let out = text
  for (const e of sorted) {
    if (text.slice(e.start, e.end) !== e.original) throw new StaleEdit(e.original)
    out = out.slice(0, e.start) + e.replacement + out.slice(e.end)
  }
  return out
}
