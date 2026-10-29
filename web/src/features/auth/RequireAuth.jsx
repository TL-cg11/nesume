// 보호 화면 가드 (D7).
//   <RequireAuth><AdminPage /></RequireAuth>                  로그인 필요
//   <RequireAuth roles={['operator']}><AuditLogsPage /></RequireAuth>   역할 제한
// 미로그인 → /login?next=<현재 경로>. 역할 불일치 → 안내 문구(존재 노출 방지를 위해 404 와 구분하지 않는다).
// operator 인데 TOTP 미등록(/auth/me mfa_required)이면 /mfa/setup 으로 보낸다(useAuth 전역 가드와 같은 규칙).
import { Navigate, useLocation } from 'react-router'
import { useAuth } from './useAuth.jsx'

export default function RequireAuth({ roles, children }) {
  const { status, me, mfaRequired } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <p className="muted">확인 중...</p>
  if (status === 'error') return <p className="error">인증 설정을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</p>
  if (status !== 'authed') {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  if (roles && me && !roles.includes(me.role)) {
    return <p className="notice">요청하신 자료는 현재 권한으로 열람할 수 없습니다.</p>
  }
  if (me?.role === 'operator' && mfaRequired && location.pathname !== '/mfa/setup') {
    return <Navigate to="/mfa/setup" replace />
  }
  return children
}
