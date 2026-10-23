// A7 맞춤법·문장 개선 API. 공통 클라이언트만 사용한다 (프론트 가이드 5절).
import { api } from '../../app/api/client.js'

// 서버 스키마(app/app/features/writing/schemas.py)의 MAX_TEXT_LEN 과 같아야 한다.
export const MAX_TEXT_LEN = 8000

export const writingApi = {
  // useLlm=false 면 규칙 검사만 한다. 입력 중 가볍게 돌릴 때 쓴다.
  proofread: (text, useLlm = true, signal) =>
    api.post('/writing/proofread', { text, use_llm: useLlm }, { signal }),

  // 수락한 제안만 반영한다. 받았던 제안을 그대로 돌려보낸다 —
  // LLM 제안은 서버가 다시 만들면 달라져 재현할 수 없다.
  apply: (text, suggestions, accepted, signal) =>
    api.post('/writing/apply', { text, suggestions, accepted }, { signal }),
}
