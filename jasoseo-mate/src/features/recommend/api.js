// C8 공고 추천 API. 공통 클라이언트(client.js)만 사용한다.
// 저장하지 않는다 — 보유 역량·필터를 받아 맞춤 공고를 돌려받을 뿐이다.
import { api } from '../../app/api/client.js'

export const recommendApi = {
  // POST /recommendations
  // payload: { held_keys[], region_codes[], job_codes[], top_k }
  recommend: (payload, opts) => api.post('/recommendations', payload, opts),

  // 공고 요건 상세(A11 /matching/analyze). posting_id 만 주고 규칙만(use_llm=false) 돌려
  // 요건을 필수/우대/언급으로 분류해 받는다. 자소서는 비운다(요건만 볼 때).
  postingDetail: (postingId, opts) =>
    api.post('/matching/analyze', { posting_id: postingId, resume_text: '', experiences: [], use_llm: false }, opts),
}
