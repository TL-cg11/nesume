import { api } from '../../app/api/client.js'

export const authApi = {
  // 로그인 직후·새로고침 때 role·is_test 확인
  me: (opts) => api.get('/auth/me', opts),
}
