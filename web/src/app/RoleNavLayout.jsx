import { Navigate } from 'react-router'
import Layout from './Layout.jsx'
import Home from './pages/Home.jsx'
import { useAuth } from '../features/auth/useAuth.jsx'

// 역할 전용 메뉴 거르기(10/29): routes.jsx의 `roles`가 있는 항목은 그 역할로 로그인했을 때만 메뉴에 보인다
// (받은 공유 = 멘토, 프롬프트 템플릿 = 운영자). 주소로 직접 들어가면 각 화면이 역할 안내를 보여준다. Layout(D)은 그대로
//
// 멘토(11/2): 멘토는 공유받은 자소서를 읽는 계정이므로 메뉴에 '받은 공유'만 남기고(roles 에 mentor 가 있는 항목),
// 대시보드 링크도 숨긴다. 로고·홈(/)은 /mentor 로 간다(RoleHome). 다른 화면은 주소로 들어가도 백엔드가 역할로 거른다.
const MENTOR_HOME = '/mentor'

export function isMentor(me) {
  return me?.role === 'mentor'
}

export default function RoleNavLayout({ navItems }) {
  const { me } = useAuth()
  const items = isMentor(me)
    ? navItems.filter((r) => r.roles?.includes('mentor'))
    : navItems.filter((r) => !r.roles || r.roles.includes(me?.role))
  return <Layout navItems={items} home={isMentor(me) ? MENTOR_HOME : '/'} />
}

// 홈(/): 멘토는 받은 공유 목록으로 보낸다. 역할 확인 전에는 대시보드 API 를 부르지 않도록 잠깐 기다린다.
export function RoleHome() {
  const { status, me } = useAuth()
  if (status === 'loading') return <p className="muted">확인 중...</p>
  if (isMentor(me)) return <Navigate to={MENTOR_HOME} replace />
  return <Home />
}
