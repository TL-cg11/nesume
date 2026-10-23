// 글 다듬기 화면이 쓰는 API 모음. 공통 클라이언트만 사용한다 (프론트 가이드 5절).
//
// 한 화면에서 세 기능을 쓴다 — A7 맞춤법·STAR, A13 글자수·문체, A14 말투 프로필.
// 셋 다 **같은 글**을 다루므로 화면을 나누지 않았다. 서버 쪽은 각각 다른 라우터다.
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

// ── A7 맞춤법·문장 개선
export const writingApi = {
  // useLlm=false 면 규칙 검사만 한다. 입력 중 가볍게 돌릴 때 쓴다.
  proofread: (text, useLlm = true, signal) =>
    api.post('/writing/proofread', { text, use_llm: useLlm }, { signal }),

  // 수락한 제안만 반영한다. 받았던 제안을 그대로 돌려보낸다 —
  // LLM 제안은 서버가 다시 만들면 달라져 재현할 수 없다.
  apply: (text, suggestions, accepted, signal) =>
    api.post('/writing/apply', { text, suggestions, accepted }, { signal }),
}

// ── A13 글자 수·문체
export const styleApi = {
  // limit 은 문항의 글자 수 상한. 비워 두면 길이는 보지 않고 문체만 본다.
  adjust: ({ text, limit, minChars, targetTone = 'formal', useLlm = true }, signal) =>
    api.post(
      '/style/adjust',
      {
        text,
        limit: limit || null,
        min_chars: minChars || null,
        target_tone: targetTone,
        use_llm: useLlm,
      },
      { signal },
    ),

  apply: (text, trims, accepted, signal) =>
    api.post('/style/apply', { text, trims, accepted }, { signal }),
}

// ── A14 말투 프로필
export const profileApi = {
  // 없으면 404 다. 호출자가 "아직 없음"으로 다룬다.
  read: (signal) => api.get('/profile/writing', { signal }),
  build: (text, signal) => api.put('/profile/writing', { text }, { signal }),
  remove: (signal) => api.delete('/profile/writing', { signal }),
}
