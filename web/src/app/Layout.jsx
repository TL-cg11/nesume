import { NavLink, Outlet } from 'react-router'
import DevTokenPanel from './dev/DevTokenPanel.jsx'
import './layout.css'

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
        {import.meta.env.DEV && <DevTokenPanel />}
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
