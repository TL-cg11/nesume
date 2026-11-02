// B13 면접 연습 API. 공통 클라이언트(app/api/client.js)만 사용한다.
import { api } from '../../app/api/client.js'

const base = (rid) => `/resumes/${rid}/interview/questions`

export const TYPES = [
  { value: 'personality', label: '인성' },
  { value: 'job', label: '직무' },
  { value: 'experience', label: '경험 검증' },
]
export const typeLabel = (v) => TYPES.find((t) => t.value === v)?.label ?? v
export const COUNT = { min: 1, max: 10, default: 5 }
export const ANSWER_MAX = 3000
export const FEEDBACK_KEYS = ['구조', '구체성', '일관성', '제안']

export const interviewApi = {
  list: (rid) => api.get(base(rid)),
  generate: (rid, type, count) => api.post(base(rid), { type, count }),
  remove: (rid, qid) => api.delete(`${base(rid)}/${qid}`),
  answers: (rid, qid) => api.get(`${base(rid)}/${qid}/answers`),
  answer: (rid, qid, answer) => api.post(`${base(rid)}/${qid}/answers`, { answer }),
}
