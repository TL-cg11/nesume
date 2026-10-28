// C14 학습 로드맵 API. 공통 클라이언트(client.js)만 사용한다.
// 서버가 토큰 sub·personal 로 소유·등급을 고정한다 — owner_id·grade 는 보내지 않는다.
import { api } from '../../app/api/client.js'

export const roadmapsApi = {
  list: (opts) => api.get('/roadmaps', opts),
  get: (id, opts) => api.get(`/roadmaps/${id}`, opts),
  // payload: { gaps:[{key,label,importance,evidence_fields[]}], weekly_hours, mode?, max_weeks? }
  create: (payload, opts) => api.post('/roadmaps', payload, opts),
  explain: (id, opts) => api.post(`/roadmaps/${id}/explain`, undefined, opts),
  updateHours: (id, weeklyHours, opts) => api.patch(`/roadmaps/${id}`, { weekly_hours: weeklyHours }, opts),
  addItem: (id, item, opts) => api.post(`/roadmaps/${id}/items`, item, opts),
  // patch: { status?, week?, position? }
  updateItem: (id, itemId, patch, opts) => api.patch(`/roadmaps/${id}/items/${itemId}`, patch, opts),
  removeItem: (id, itemId, opts) => api.delete(`/roadmaps/${id}/items/${itemId}`, opts),
}
