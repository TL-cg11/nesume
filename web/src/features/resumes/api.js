// B4 자소서 API 호출. 공통 클라이언트(app/api/client.js)만 사용한다.
import { api } from '../../app/api/client.js'

const q = (rid, qid) => `/resumes/${rid}/questions/${qid}`

export const resumesApi = {
  list: () => api.get('/resumes'),
  create: (data) => api.post('/resumes', data),
  get: (rid) => api.get(`/resumes/${rid}`),
  update: (rid, data) => api.patch(`/resumes/${rid}`, data),
  remove: (rid) => api.delete(`/resumes/${rid}`),

  createQuestion: (rid, data) => api.post(`/resumes/${rid}/questions`, data),
  updateQuestion: (rid, qid, data) => api.patch(q(rid, qid), data),
  removeQuestion: (rid, qid) => api.delete(q(rid, qid)),

  saveVersion: (rid, qid, body) => api.post(`${q(rid, qid)}/versions`, { body }),
  // includeEnded: 만료·취소된 멘토 공유 태그도 포함(B10 공유 버전 태그)
  listVersions: (rid, qid, includeEnded = false) =>
    api.get(`${q(rid, qid)}/versions${includeEnded ? '?include_ended=true' : ''}`),
  getVersion: (rid, qid, vid) => api.get(`${q(rid, qid)}/versions/${vid}`),
  diff: (rid, qid, from, to) => api.get(`${q(rid, qid)}/versions/diff?from=${from}&to=${to}`),
  restore: (rid, qid, vid) => api.post(`${q(rid, qid)}/versions/${vid}/restore`),
}

// B10 멘토 공유(작성자용)
export const sharesApi = {
  list: (rid) => api.get(`/resumes/${rid}/shares`),
  create: (rid, data) => api.post(`/resumes/${rid}/shares`, data),
  extend: (sid, endDate) => api.post(`/shares/${sid}/extend`, { end_date: endDate }),
  rename: (sid, label) => api.patch(`/shares/${sid}`, { mentor_label: label }),
  revoke: (sid) => api.delete(`/shares/${sid}`),
}
