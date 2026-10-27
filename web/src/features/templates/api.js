// B9 프롬프트 템플릿(운영자 전용). 공통 클라이언트(app/api/client.js)만 사용한다.
import { api } from '../../app/api/client.js'

export const templatesApi = {
  list: () => api.get('/templates'),
  create: (data) => api.post('/templates', data),
  versions: (name) => api.get(`/templates/${encodeURIComponent(name)}/versions`),
  newVersion: (name, data) => api.post(`/templates/${encodeURIComponent(name)}/versions`, data),
  activate: (id) => api.put(`/templates/${id}/activate`),
}

// 본문의 {{변수}}를 뽑는다(서버와 같은 규칙). 변수 목록을 자동으로 채우는 데 쓴다
export const placeholders = (body) => [...new Set([...body.matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,49})\s*\}\}/g)].map((m) => m[1]))]

export const errorText = (e) => {
  if (e.code === 'mfa_required') return 'MFA(TOTP) 등록 후 활성 전환할 수 있습니다.'
  if (e.code === 'mfa_session_expired') return '보안을 위해 다시 로그인한 뒤 활성 전환해 주세요.'
  if (e.code === 'template_variables_mismatch') return '본문의 {{변수}}와 변수 목록이 다릅니다.'
  if (e.status === 403) return '운영자만 사용할 수 있습니다.'
  return e.message
}
