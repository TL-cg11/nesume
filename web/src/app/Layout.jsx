import { useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router'
import Icon, { IconSprite } from './Icons.jsx'
import ThemeToggle from './ThemeToggle.jsx'
import { useAuth } from '../features/auth/useAuth.jsx'

const ROLE_LABEL = { user: '일반 사용자', mentor: '멘토', operator: '운영자', system: '시스템' }

// 경로 → 아이콘 + 그룹(발표 시안 구성). routes.jsx 는 nav 라벨만 들고, 표시용 메타는 여기서 붙인다.
const NAV_META = {
  resumes: { icon: 'file', group: '워크스페이스' },
  experiences: { icon: 'case', group: '워크스페이스' },
  writing: { icon: 'spark', group: 'AI 도구' },
  interview: { icon: 'msg', group: 'AI 도구' },
  // C 공고 추천·학습 로드맵·지원 현황
  recommend: { icon: 'dash', group: '취업 준비' },
  learning: { icon: 'spark', group: '취업 준비' },
  applications: { icon: 'case', group: '취업 준비' },
  github: { icon: 'git', group: '소개' },
  // B17 멘토 공유, B11 AI 사용 기록(발표 시안의 '관리' 그룹)
  mentor: { icon: 'user', group: '관리' },
  'ai-logs': { icon: 'shield', group: '관리' }, // B11 AI 사용 기록(운영자). 10/29 프롬프트 템플릿 대신
  'admin/dashboard': { icon: 'dash', group: '관리' }, // D14·D15 운영 대시보드
  'admin/users': { icon: 'user', group: '관리' }, // D6 역할 관리
}
const GROUP_ORDER = ['워크스페이스', 'AI 도구', '취업 준비', '소개', '관리', '기타']

function groupNav(navItems) {
  const groups = new Map()
  for (const item of navItems) {
    const meta = NAV_META[item.path] || { icon: 'file', group: '기타' }
    if (!groups.has(meta.group)) groups.set(meta.group, [])
    groups.get(meta.group).push({ ...item, icon: meta.icon })
  }
  return GROUP_ORDER.filter((g) => groups.has(g)).map((g) => ({ label: g, items: groups.get(g) }))
}

function pageTitle(pathname, navItems) {
  const seg = pathname.split('/')[1]
  if (!seg) return '대시보드'
  // 두 단계 경로(admin/dashboard, admin/users)는 전체 경로로 먼저 찾는다
  const hit = navItems.find((n) => pathname === `/${n.path}` || pathname.startsWith(`/${n.path}/`)) ?? navItems.find((n) => n.path === seg)
  if (hit) return hit.nav
  const label = { login: '로그인', signup: '계정 만들기', confirm: '이메일 확인', forgot: '비밀번호 재설정', mfa: '인증', admin: '운영' }
  return label[seg] || 'nesume'
}

function UserBlock() {
  const { status, me, email, logout } = useAuth()
  if (status === 'loading') return <div className="app-user muted">확인 중...</div>
  if (status !== 'authed') {
    return (
      <Link to="/login" className="app-login-link">
        <Icon name="user" /> 로그인
      </Link>
    )
  }
  return (
    <div className="app-user">
      <div className="app-user-id">
        <span className="app-user-av">
          <Icon name="user" />
        </span>
        <span className="app-user-info">
          <span className="app-user-name" title={email ?? ''}>
            {email ?? me?.username ?? ''}
          </span>
          <span className="app-user-role">{me ? ROLE_LABEL[me.role] ?? me.role : ''}</span>
        </span>
      </div>
      {/* 이메일을 가리지 않도록 사용자 정보 아래 줄에 작게 둔다(모바일 상단 바에서는 옆에 아이콘만) */}
      <button type="button" className="secondary app-user-logout" onClick={logout} title="로그아웃" aria-label="로그아웃">
        <Icon name="logout" />
        <span className="app-user-logout-label">로그아웃</span>
      </button>
    </div>
  )
}

// home: 로고·대시보드가 가리키는 곳. '/' 가 아니면(멘토 → /mentor) 대시보드 링크를 숨긴다(RoleNavLayout)
export default function Layout({ navItems, home = '/' }) {
  const location = useLocation()
  const [navOpen, setNavOpen] = useState(false)
  const groups = groupNav(navItems)
  const closeNav = () => setNavOpen(false)

  return (
    <div className="app-shell">
      <IconSprite />
      <aside className={`app-side${navOpen ? ' open' : ''}`}>
        <button
          type="button"
          className="app-menu-btn"
          onClick={() => setNavOpen((v) => !v)}
          aria-label="메뉴 열기"
          aria-expanded={navOpen}
        >
          <Icon name="menu" />
        </button>
        <Link to={home} className="app-brand" onClick={closeNav}>
          <span className="app-brand-mark">
            <Icon name="file" />
          </span>
          <span className="app-brand-text">
            <span className="app-brand-name">nesume</span>
            <span className="app-brand-cap">AI CAREER WORKSPACE</span>
          </span>
        </Link>

        <nav className="app-nav">
          {home === '/' && (
            <div className="app-nav-group">
              <NavLink to="/" end onClick={closeNav}>
                <Icon name="home" /> 대시보드
              </NavLink>
            </div>
          )}
          {groups.map((group) => (
            <div className="app-nav-group" key={group.label}>
              <span className="app-nav-label">{group.label}</span>
              {group.items.map((item) => (
                <NavLink key={item.path} to={`/${item.path}`} onClick={closeNav}>
                  <Icon name={item.icon} /> {item.nav}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="app-side-bottom">
          <UserBlock />
        </div>
      </aside>

      <div className="app-main-col">
        <header className="app-topbar">
          <span className="app-topbar-title">{pageTitle(location.pathname, navItems)}</span>
          <div className="app-topbar-right">
            <span className="app-env">dev · localhost</span>
            <ThemeToggle />
          </div>
        </header>
        <main className="app-main">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
