// AI 사용 기록(B11 화면, 10/29). 공통 클라이언트(app/api/client.js)만 사용한다. 운영자 MFA 세션 필요
import { api } from '../../app/api/client.js'

const qs = (params) => {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (Array.isArray(v)) v.forEach((x) => q.append(k, x))
    else if (v !== undefined && v !== null && v !== '') q.append(k, v)
  })
  return q.toString()
}

export const auditApi = {
  list: (params, signal) => api.get(`/audit-logs?${qs(params)}`, { signal }),
  emails: (ids) => (ids.length ? api.get(`/audit-logs/emails?${qs({ user_id: ids })}`) : Promise.resolve({})),
  lookup: (email) => api.get(`/audit-logs/lookup?${qs({ email })}`),
}

export const errorText = (e) => {
  if (e.code === 'mfa_required') return 'MFA(TOTP)를 등록한 운영자만 볼 수 있습니다.'
  if (e.code === 'mfa_session_expired') return '보안을 위해 다시 로그인한 뒤 확인해 주세요.'
  if (e.status === 403) return '운영자만 사용할 수 있습니다.'
  return e.message
}
