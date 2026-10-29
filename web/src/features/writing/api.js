// 글 다듬기 화면이 쓰는 API 모음. 공통 클라이언트만 사용한다 (프론트 가이드 5절).
//
//   검사·교정 탭  맞춤법(A7 /writing/proofread) · STAR(/writing/star) — 따로 누른다
//   다시 쓰기 탭  내 말투 샘플로 다시 쓰기(A6 /writing/rewrite + style_sample)
import { api } from '../../app/api/client.js'

// 서버 스키마의 MAX_TEXT_LEN 과 같아야 한다 (writing/schemas.py 8000).
export const MAX_TEXT_LEN = 8000

// 문체 이름. 서버 tone.py 의 TONE_NAMES 와 같아야 한다.
export const TONE_NAMES = {
  formal: '합니다체',
  polite: '해요체',
  plain: '했다체',
  nominal: '음슴체',
}

export const reviewApi = {
  // 규칙(맞춤법·띄어쓰기) + AI 문장 제안
  spelling: (text, signal) => api.post('/writing/proofread', { text, use_llm: true }, { signal }),
  // STAR 네 요소를 AI가 판정한다. AI를 못 쓰면 서버가 규칙 판정으로 내려간다
  star: (text, signal) => api.post('/writing/star', { text }, { signal }),
}

// ── A6 다시 쓰기 (내 말투)
//
// ★ **고른 구간**을 다룬다. 그래서 상한이 MAX_TEXT_LEN 과 다르다 —
//   서버 rewrite.py 의 MAX_SELECTION_LEN(5,000 × 4조각)과 같아야 한다.
export const MAX_SELECTION_LEN = 20000

// 한 번에 모델로 보내는 조각 크기. 이보다 길면 서버가 나눠 보낸다.
export const CHUNK_CHARS = 5000

// 돌려받는 후보 수 (서버 CANDIDATE_COUNT).
export const CANDIDATE_COUNT = 3

// 말투 샘플 길이 (서버 rewrite.py MIN_SAMPLE_CHARS · MAX_SAMPLE_CHARS).
export const MIN_SAMPLE_CHARS = 100
export const MAX_SAMPLE_CHARS = 3000

export const rewriteApi = {
  rewrite: ({ text, tone = 'formal', styleSample }, signal) =>
    api.post(
      '/writing/rewrite',
      { text, tone, length: 'similar', keywords: [], use_llm: true, style_sample: styleSample },
      { signal },
    ),

  // 고른 후보를 새 버전으로 저장한다 (B4, source="ai").
  // 문항 맥락이 있을 때만 쓸 수 있다 — 글 다듬기 화면은 기본적으로 저장하지 않는다.
  apply: ({ resumeId, questionId, body }, signal) =>
    api.post(
      '/writing/rewrite/apply',
      { resume_id: resumeId, question_id: questionId, body },
      { signal },
    ),
}
