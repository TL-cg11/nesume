// B10·B17 멘토용 공유 API. 공통 클라이언트(app/api/client.js)만 사용한다.
import { api } from '../../app/api/client.js'

const base = (sid) => `/mentor/shares/${sid}`

export const mentorApi = {
  list: () => api.get('/mentor/shares'),
  get: (sid) => api.get(base(sid)),
  addComment: (sid, data) => api.post(`${base(sid)}/comments`, data),
  editComment: (sid, cid, body) => api.patch(`${base(sid)}/comments/${cid}`, { body }),
  removeComment: (sid, cid) => api.delete(`${base(sid)}/comments/${cid}`),
}

export const roleError = (e) =>
  e.status === 403 ? '멘토 계정에서만 볼 수 있습니다.' : e.status === 404 ? '공유가 끝났거나 찾을 수 없습니다.' : e.message
