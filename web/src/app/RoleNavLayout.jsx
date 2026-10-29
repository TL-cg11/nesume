import Layout from './Layout.jsx'
import { useAuth } from '../features/auth/useAuth.jsx'

// 역할 전용 메뉴 거르기(10/29): routes.jsx의 `roles`가 있는 항목은 그 역할로 로그인했을 때만 메뉴에 보인다
// (받은 공유 = 멘토, 프롬프트 템플릿 = 운영자). 주소로 직접 들어가면 각 화면이 역할 안내를 보여준다. Layout(D)은 그대로
export default function RoleNavLayout({ navItems }) {
  const { me } = useAuth()
  return <Layout navItems={navItems.filter((r) => !r.roles || r.roles.includes(me?.role))} />
}
