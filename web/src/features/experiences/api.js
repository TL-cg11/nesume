// B5 경험 데이터 API. 공통 클라이언트만 사용한다.
import { api } from '../../app/api/client.js'

const links = (rid, qid) => `/resumes/${rid}/questions/${qid}/experiences`

export const experiencesApi = {
  list: (tags = []) => {
    const qs = new URLSearchParams()
    tags.forEach((t) => qs.append('tags', t))
    const s = qs.toString()
    return api.get(`/experiences${s ? `?${s}` : ''}`)
  },
  create: (data) => api.post('/experiences', data),
  update: (id, data) => api.patch(`/experiences/${id}`, data),
  get: (id) => api.get(`/experiences/${id}`),
  remove: (id) => api.delete(`/experiences/${id}`),
  // B14 GitHub 소개 초안(유형 GitHub). 결과의 experience_draft로 폼을 채운다
  githubDraft: (data) => api.post('/experiences/github/draft', data),

  listLinked: (rid, qid) => api.get(links(rid, qid)),
  link: (rid, qid, experienceId) => api.post(links(rid, qid), { experience_id: experienceId }),
  unlink: (rid, qid, experienceId) => api.delete(`${links(rid, qid)}/${experienceId}`),
}
