// C15 지원 현황 API. 공통 클라이언트(client.js)만 사용한다.
import { api } from '../../app/api/client.js'

export const applicationsApi = {
  list: () => api.get('/applications'),
  stats: () => api.get('/applications/stats'),
  dueSoon: () => api.get('/applications/due-soon'),
  create: (data) => api.post('/applications', data),
  updateStatus: (id, status) => api.patch(`/applications/${id}`, { status }),
  remove: (id) => api.delete(`/applications/${id}`),
  // 칸반 한 열의 새 순서(위→아래). 다른 열에서 온 카드는 이 상태로 바뀐다
  reorder: (status, ids) => api.put('/applications/order', { status, ids }),
}
