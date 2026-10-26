// 라이트/다크 수동 전환 버튼. 선택은 localStorage 에 기억한다(뷰어별 편의, 서버에 보내지 않음).
// data-theme 속성이 OS 설정(prefers-color-scheme)보다 우선한다(theme.css). 미설정이면 OS 를 따른다.
import { useEffect, useState } from 'react'
import Icon from './Icons.jsx'

const KEY = 'nesume-theme'

function osPrefersDark() {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches
}

function savedTheme() {
  try {
    const t = localStorage.getItem(KEY)
    if (t === 'light' || t === 'dark') return t
  } catch {
    /* private 모드 등: 저장 불가 → OS 설정을 따른다 */
  }
  return null // null = OS 설정을 따름
}

export default function ThemeToggle() {
  // explicit: 사용자가 고른 값(light/dark) 또는 null(OS 따름)
  const [explicit, setExplicit] = useState(savedTheme)
  const effective = explicit ?? (osPrefersDark() ? 'dark' : 'light')

  // explicit 이 null 이면 OS 변경을 따라 아이콘을 갱신한다.
  useEffect(() => {
    if (explicit) return
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const onChange = () => setExplicit((v) => v) // 리렌더로 effective 재계산
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [explicit])

  const toggle = () => {
    const next = effective === 'dark' ? 'light' : 'dark'
    document.documentElement.setAttribute('data-theme', next)
    try {
      localStorage.setItem(KEY, next)
    } catch {
      /* 저장 실패해도 이번 세션에는 적용된다 */
    }
    setExplicit(next)
  }

  const toDark = effective === 'light'
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={toDark ? '다크 모드로 전환' : '라이트 모드로 전환'}
      title={toDark ? '다크 모드' : '라이트 모드'}
    >
      <Icon name={toDark ? 'moon' : 'sun'} />
    </button>
  )
}
