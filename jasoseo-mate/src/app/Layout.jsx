import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import DevTokenPanel from './dev/DevTokenPanel.jsx'

export default function Layout({ navItems }) {
  const [mobileNav, setMobileNav] = useState(false)
  const location = useLocation()
  const active = navItems.find(
    (n) => location.pathname === `/${n.path}` || location.pathname.startsWith(`/${n.path}/`),
  )
  const pageTitle = active?.nav ?? '홈'

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNav ? 'sidebar-open' : ''}`}>
        <div className="brand">
          <div className="brand-mark">자</div>
          <div className="grow">
            <div className="brand-name">자소서 메이트</div>
            <div className="brand-caption">AI CAREER STUDIO</div>
          </div>
          <button className="icon-button sidebar-close" onClick={() => setMobileNav(false)} aria-label="메뉴 닫기">
            ×
          </button>
        </div>
        <nav className="nav-group">
          <div className="nav-label">워크스페이스</div>
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={`/${item.path}`}
              className={({ isActive }) => `nav-item ${isActive ? 'nav-item-active' : ''}`}
              onClick={() => setMobileNav(false)}
            >
              {item.nav}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="plan-card">
            <div className="plan-card-title">로컬 데모</div>
            <p className="plan-card-body">가이드 스택(React · 순수 CSS) 프로토타입. AI·서버 연동 전.</p>
          </div>
        </div>
      </aside>

      {mobileNav && <button aria-label="메뉴 닫기" className="mobile-scrim" onClick={() => setMobileNav(false)} />}

      <main className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-button topbar-menu" onClick={() => setMobileNav(true)} aria-label="메뉴 열기">
              ≡
            </button>
            <span className="topbar-title">{pageTitle}</span>
          </div>
          <div className="topbar-right">
            <span className="demo-badge">로컬 데모 모드</span>
            {import.meta.env.DEV && <DevTokenPanel />}
          </div>
        </header>
        <div className="page-content">
          <Outlet />
          <footer className="app-footer">
            © 2026 자소서 메이트 · 학교 프로젝트 MVP · 데모에는 실제 개인정보를 입력하지 마세요.
          </footer>
        </div>
      </main>
    </div>
  )
}
