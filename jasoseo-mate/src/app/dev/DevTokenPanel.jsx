// 로컬 개발 전용 토큰 입력란 (B4). D7 로그인 화면 추합 시 삭제한다.
// Layout에서 import.meta.env.DEV일 때만 렌더링하므로 운영 빌드에는 포함되지 않는다.
// VITE_DEV_TOKEN 이 있으면 자동 적용한다(새로고침해도 유지) — E2E 테스트 편의.
//   예: VITE_DEV_TOKEN=<accessToken> API_PROXY_TARGET=http://localhost:8000 npm run dev
import { useEffect, useState } from 'react'
import { setTokenProvider } from '../api/client.js'

const DEV_TOKEN = import.meta.env.VITE_DEV_TOKEN || ''

export default function DevTokenPanel() {
  const [value, setValue] = useState(DEV_TOKEN)
  const [applied, setApplied] = useState(false)

  // VITE_DEV_TOKEN 이 주어졌으면 마운트 시 자동 적용
  useEffect(() => {
    if (DEV_TOKEN) {
      setTokenProvider(async () => DEV_TOKEN)
      setApplied(true)
    }
  }, [])

  const apply = (e) => {
    e.preventDefault()
    const token = value.trim()
    setTokenProvider(async () => token || null)
    setApplied(Boolean(token))
  }

  return (
    <form className="dev-token" onSubmit={apply}>
      <span className="dev-token-label">DEV 토큰</span>
      <input
        type="password"
        placeholder="cognito-local Access Token"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        aria-label="개발용 액세스 토큰"
      />
      <button type="submit">적용</button>
      <span className="dev-token-state">{applied ? '적용됨' : '미적용'}</span>
    </form>
  )
}
