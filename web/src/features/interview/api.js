// B13 모의 면접 API. 공통 클라이언트(app/api/client.js)만 사용한다.
import { api } from '../../app/api/client.js'

const base = (rid) => `/resumes/${rid}/interviews`

export const MAIN = { min: 3, max: 7, default: 5 }
export const ANSWER_MAX = 3000
export const FEEDBACK_KEYS = ['구조', '구체성', '일관성', '질문별', '제안']

export const interviewApi = {
  list: (rid) => api.get(base(rid)),
  get: (rid, sid) => api.get(`${base(rid)}/${sid}`),
  start: (rid, mainCount) => api.post(base(rid), { main_count: mainCount }),
  answer: (rid, sid, answer) => api.post(`${base(rid)}/${sid}/answers`, { answer }),
  finish: (rid, sid) => api.post(`${base(rid)}/${sid}/finish`),
  feedback: (rid, sid) => api.post(`${base(rid)}/${sid}/feedback`),
  remove: (rid, sid) => api.delete(`${base(rid)}/${sid}`),
}
