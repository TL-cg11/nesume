// D6 운영자 역할 관리. 공통 클라이언트(app/api/client.js)만 사용한다.
import { api } from '../../app/api/client.js'

export const adminApi = {
  // email 이 비면 운영자·멘토 목록, 있으면 이메일 앞부분 검색(최대 20명)
  users: (email) => api.get(email ? `/admin/users?email=${encodeURIComponent(email)}` : '/admin/users'),
  changeRole: (userId, role) => api.put(`/admin/users/${encodeURIComponent(userId)}/role`, { role }),
}

export const ROLE_LABEL = { user: '일반 사용자', mentor: '멘토', operator: '운영자', system: '시스템', invalid: '설정 오류' }
export const ASSIGNABLE_ROLES = ['user', 'mentor', 'operator']

export const errorText = (e) => {
  if (e.code === 'mfa_session_expired') return '보안을 위해 다시 로그인한 뒤 시도해 주세요(운영자 기능은 로그인 후 일정 시간만 열립니다).'
  if (e.code === 'mfa_required') return '인증 앱(TOTP)을 먼저 등록해 주세요.'
  if (e.code === 'self_change_forbidden') return '자기 자신의 역할은 바꿀 수 없습니다.'
  if (e.code === 'system_account_protected') return '시스템(배치) 계정의 역할은 바꿀 수 없습니다.'
  if (e.code === 'not_found') return '사용자를 찾을 수 없습니다(탈퇴 예약 또는 삭제된 계정).'
  if (e.status === 422) return '검색어에 쓸 수 없는 문자가 있습니다.'
  if (e.status === 403) return '운영자만 사용할 수 있습니다.'
  return e.message
}
