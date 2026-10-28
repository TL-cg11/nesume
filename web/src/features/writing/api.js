// 글 다듬기 화면이 쓰는 API 모음. 공통 클라이언트만 사용한다 (프론트 가이드 5절).
//
// 화면은 탭 둘이지만 서버는 기능별 라우터 그대로다.
//   검사·교정 탭  = A7 /writing/proofread + A13 /style/adjust 를 **한 번에** 부른다
//   다시 쓰기 탭  = A6 /writing/rewrite + A14 /profile/writing (말투)
import { api } from '../../app/api/client.js'

// 서버 스키마의 MAX_TEXT_LEN 과 같아야 한다.
// writing/schemas.py · style/schemas.py · profile/schemas.py 모두 8000 이다.
export const MAX_TEXT_LEN = 8000

// A14 — 말투 프로필을 만들 수 있는 최소 글자 수 (profile/extract.py MIN_SOURCE_CHARS).
// 표본이 적으면 말투가 아니라 그 글의 우연이라 서버가 거절한다.
export const MIN_PROFILE_CHARS = 1000

// 문체 이름. 서버 tone.py 의 TONE_NAMES 와 같아야 한다.
export const TONE_NAMES = {
  formal: '합니다체',
  polite: '해요체',
  plain: '했다체',
  nominal: '음슴체',
}

// ── 검사·교정 (A7 + A13)
//
// ★ 두 검사를 **동시에** 부른다. 사용자는 "검사" 한 번만 누른다.
//   제안 반영은 서버 /apply 를 쓰지 않고 화면에서 한다(edits.js) — 두 서버의 제안을
//   한 목록에서 고르므로, 한쪽 /apply 로는 다른 쪽 제안을 반영할 수 없다.
export const reviewApi = {
  check: async ({ text, limit, targetTone }, signal) => {
    const [proofread, style] = await Promise.all([
      api.post('/writing/proofread', { text, use_llm: true }, { signal }),
      api.post(
        '/style/adjust',
        { text, limit: limit || null, min_chars: null, target_tone: targetTone, use_llm: true },
        { signal },
      ),
    ])
    return { proofread, style }
  },
}

// ── A14 말투 프로필
export const profileApi = {
  // 없으면 404 다. 호출자가 "아직 없음"으로 다룬다.
  read: (signal) => api.get('/profile/writing', { signal }),
  build: (text, signal) => api.put('/profile/writing', { text }, { signal }),
  remove: (signal) => api.delete('/profile/writing', { signal }),
}

// ── A6 리라이팅
//
// ★ **고른 구간**을 다룬다. 그래서 상한이 MAX_TEXT_LEN 과 다르다 —
//   서버 rewrite.py 의 MAX_SELECTION_LEN(5,000 × 4조각)과 같아야 한다.
export const MAX_SELECTION_LEN = 20000

// 한 번에 모델로 보내는 조각 크기. 이보다 길면 서버가 나눠 보낸다.
export const CHUNK_CHARS = 5000

// 돌려받는 후보 수 (서버 CANDIDATE_COUNT).
export const CANDIDATE_COUNT = 3

// 길이 옵션. 서버 rewrite.py 의 LENGTH_NAMES 와 같아야 한다.
export const LENGTH_NAMES = {
  shorter: '짧게',
  similar: '비슷하게',
  longer: '길게',
}

// 키워드 개수·길이 상한 (서버 MAX_KEYWORDS · MAX_KEYWORD_LEN).
export const MAX_KEYWORDS = 10
export const MAX_KEYWORD_LEN = 30

export const rewriteApi = {
  rewrite: ({ text, tone = 'formal', length = 'similar', keywords = [] }, signal) =>
    api.post('/writing/rewrite', { text, tone, length, keywords, use_llm: true }, { signal }),

  // 고른 후보를 새 버전으로 저장한다 (B4, source="ai").
  // 문항 맥락이 있을 때만 쓸 수 있다 — 글 다듬기 화면은 기본적으로 저장하지 않는다.
  apply: ({ resumeId, questionId, body }, signal) =>
    api.post(
      '/writing/rewrite/apply',
      { resume_id: resumeId, question_id: questionId, body },
      { signal },
    ),
}
