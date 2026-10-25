import { Link, NavLink, Outlet } from 'react-router'
import { useAuth } from '../features/auth/useAuth.jsx'

const ROLE_LABEL = { user: '사용자', mentor: '멘토', operator: '운영자', system: '시스템' }

function UserMenu() {
  const { status, me, email, logout } = useAuth()
  if (status === 'loading') return <div className="auth-user muted">확인 중...</div>
  if (status !== 'authed') {
    return (
      <div className="auth-user">
        <Link to="/login">로그인</Link>
      </div>
    )
  }
  return (
    <div className="auth-user">
      <span className="auth-user-email" title={email ?? ''}>
        {email ?? me?.username ?? ''}
      </span>
      {me && <span className="auth-role">{ROLE_LABEL[me.role] ?? me.role}</span>}
      <button type="button" className="secondary" onClick={logout}>
        로그아웃
      </button>
    </div>
  )
}

export default function Layout({ navItems }) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <NavLink to="/" className="app-brand">
          nesume
        </NavLink>
        <nav className="app-nav">
          {navItems.map((item) => (
            <NavLink key={item.path} to={`/${item.path}`}>
              {item.nav}
            </NavLink>
          ))}
        </nav>
        <UserMenu />
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
