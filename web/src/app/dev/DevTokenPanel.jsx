// 로컬 개발 전용 토큰 입력란 (B4). D7 로그인 화면 추합 시 삭제한다.
// Layout에서 import.meta.env.DEV일 때만 렌더링하므로 운영 빌드에는 포함되지 않는다.
// 토큰은 메모리에만 보관한다(새로고침 시 다시 입력).
import { useState } from 'react'
import { setTokenProvider } from '../api/client.js'

export default function DevTokenPanel() {
  const [value, setValue] = useState('')
  const [applied, setApplied] = useState(false)

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
