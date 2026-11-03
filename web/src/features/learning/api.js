// C14 학습 로드맵 API. 공통 클라이언트(client.js)만 사용한다.
// 서버가 토큰 sub·personal 로 소유·등급을 고정한다 — owner_id·grade 는 보내지 않는다.
import { api } from '../../app/api/client.js'

export const roadmapsApi = {
  list: (opts) => api.get('/roadmaps', opts),
  get: (id, opts) => api.get(`/roadmaps/${id}`, opts),
  // payload: { gaps:[{key,label,importance,evidence_fields[]}], weekly_hours, mode?, max_weeks? }
  create: (payload, opts) => api.post('/roadmaps', payload, opts),
  remove: (id, opts) => api.delete(`/roadmaps/${id}`, opts),
  // 초안 → 저장본(+이름). 저장 취소는 없다(삭제로). 저장본이 10개면 replaceOldest(사용자 확인)일 때만
  // 가장 오래된 것을 지우고 저장, 아니면 409
  save: (id, name, { replaceOldest = false } = {}, opts) =>
    api.patch(`/roadmaps/${id}`, { save: true, name: name || null, replace_oldest: replaceOldest }, opts),
  updateHours: (id, weeklyHours, opts) => api.patch(`/roadmaps/${id}`, { weekly_hours: weeklyHours }, opts),
  addItem: (id, item, opts) => api.post(`/roadmaps/${id}/items`, item, opts),
  // patch: { status?, week?, position? }
  updateItem: (id, itemId, patch, opts) => api.patch(`/roadmaps/${id}/items/${itemId}`, patch, opts),
  removeItem: (id, itemId, opts) => api.delete(`/roadmaps/${id}/items/${itemId}`, opts),
  // "이 역량 강좌 전체 보기": { mode?: 'online'|'offline', page, size } → { total, page, size, items[] }
  candidates: (id, itemId, { mode, page = 1, size = 20 } = {}, opts) => {
    const q = new URLSearchParams({ page: String(page), size: String(size) })
    if (mode) q.set('mode', mode)
    return api.get(`/roadmaps/${id}/items/${itemId}/candidates?${q}`, opts)
  },
  // 목록에서 고른 강좌 → 교체(replace=true) 또는 같은 역량·주차에 추가
  pick: (id, itemId, { content_id, replace = false }, opts) =>
    api.post(`/roadmaps/${id}/items/${itemId}/candidates`, { content_id, replace }, opts),
}

// C10 맞춤 학습 갭: 자소서 + 공고 → 배워야 할 역량(필수·우대, 중요도순). 자소서 원문은 서버 안에서만 쓴다.
// fieldIndex: 모집분야가 여럿인 공고에서 그 분야 글로만 분석(없으면 공고 전체)
export const learningGapsApi = {
  forPosting: (resumeId, postingId, fieldIndex = null, opts) =>
    api.post(
      '/learning-gaps',
      { resume_id: resumeId, posting_id: postingId, ...(fieldIndex != null ? { field_index: fieldIndex } : {}) },
      opts,
    ),
}
