// 검사 결과(A7 제안 + A13 줄이기)를 한 목록으로 묶고, 고른 것만 글에 반영한다.
//
// ★ 서버 /writing/apply · /style/apply 를 쓰지 않는 이유: 두 서버의 제안을 한 목록에서
//   고르는데, 한쪽 /apply 는 다른 쪽 제안 모양을 모른다. 대신 서버와 같은 두 가지를 지킨다.
//     - 위치의 글이 제안을 받을 때와 같은지 본다 (서버 409 와 같은 판단)
//     - 겹치는 제안은 함께 고를 수 없다

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

// 서버 응답 → 공통 모양 { id, start, end, original, replacement, reason, tags, before?, after? }
export function toEdits(text, proofread, style) {
  const fixes = proofread.suggestions
    .filter((s) => s.is_replacement)
    .map((s) => ({
      id: `p:${s.id}`,
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
    }))

  const trims = style.trims.map((t) => ({
    id: `t:${t.id}`,
    start: t.start,
    end: t.end,
    original: t.original,
    replacement: t.replacement,
    reason: t.reason,
    tags: [
      { label: `-${t.saved}자` },
      ...(t.confidence === 'medium' ? [{ label: '확인 필요', tone: 'check' }] : []),
    ],
  }))

  return [...fixes, ...trims]
    .map((e) => withContext(text, e))
    .sort((a, b) => a.start - b.start || a.end - b.end)
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
