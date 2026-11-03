// C8 공고 추천 API. 공통 클라이언트(client.js)만 사용한다.
// 저장하지 않는다 — 보유 역량·필터를 받아 맞춤 공고를 돌려받을 뿐이다.
import { api } from '../../app/api/client.js'

export const recommendApi = {
  // POST /recommendations
  // payload: { held_keys[], region_codes[], job_codes[], top_k }
  recommend: (payload, opts) => api.post('/recommendations', payload, opts),

  // 공고 상세 원문(C4 GET /postings/{id}) — `라벨: 값` 목록 + 직무내용 원문 + 원문 링크.
  // (A11 키워드 추출은 매칭용이라 화면 표시엔 쓰지 않는다)
  postingDetail: (postingId, opts) => api.get(`/postings/${postingId}`, opts),
}
