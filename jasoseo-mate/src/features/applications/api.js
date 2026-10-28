// C15 지원 현황 API. 공통 클라이언트(client.js)만 사용한다.
import { api } from '../../app/api/client.js'

export const applicationsApi = {
  list: () => api.get('/applications'),
  stats: () => api.get('/applications/stats'),
  dueSoon: () => api.get('/applications/due-soon'),
  create: (data) => api.post('/applications', data),
  updateStatus: (id, status) => api.patch(`/applications/${id}`, { status }),
  remove: (id) => api.delete(`/applications/${id}`),
}
