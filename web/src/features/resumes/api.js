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
  listVersions: (rid, qid) => api.get(`${q(rid, qid)}/versions`),
  getVersion: (rid, qid, vid) => api.get(`${q(rid, qid)}/versions/${vid}`),
  diff: (rid, qid, from, to) => api.get(`${q(rid, qid)}/versions/diff?from=${from}&to=${to}`),
  restore: (rid, qid, vid) => api.post(`${q(rid, qid)}/versions/${vid}/restore`),
}
