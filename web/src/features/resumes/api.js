// B4 자소서 API 호출. 공통 클라이언트(app/api/client.js)만 사용한다.
import { api } from '../../app/api/client.js'

const q = (rid, qid) => `/resumes/${rid}/questions/${qid}`

// '자기소개서 작성' 버튼(목록·홈)이 바로 만들 때의 제목. 상세 화면에서 바꾼다(10/28 결정)
export const UNTITLED = '제목 없는 자기소개서'

export const resumesApi = {
  // 사용자당 자소서는 최대 50개(4.56)라 한 번에 모두 받는다(API 최대 100)
  list: () => api.get('/resumes?limit=100'),
  // 홈 대시보드 집계(B, 4.54)
  dashboard: (opts) => api.get('/resumes/dashboard', opts),
  create: (data) => api.post('/resumes', data),
  createUntitled: () => api.post('/resumes', { title: UNTITLED }),
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
  // 문항당 50개 상한이라 사용자가 골라 지운다(4.56). 지원 기록·공유 중인 버전은 409
  removeVersion: (rid, qid, vid) => api.delete(`${q(rid, qid)}/versions/${vid}`),
}

// B10 멘토 공유(작성자용)
export const sharesApi = {
  list: (rid) => api.get(`/resumes/${rid}/shares`),
  create: (rid, data) => api.post(`/resumes/${rid}/shares`, data),
  extend: (sid, endDate) => api.post(`/shares/${sid}/extend`, { end_date: endDate }),
  rename: (sid, label) => api.patch(`/shares/${sid}`, { mentor_label: label }),
  revoke: (sid) => api.delete(`/shares/${sid}`),
  // B17 멘토 코멘트(작성자는 원문으로 보고 확인 표시만 한다)
  comments: (sid) => api.get(`/shares/${sid}/comments`),
  markRead: (sid, cid) => api.post(`/shares/${sid}/comments/${cid}/read`),
}
