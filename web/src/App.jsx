import { useEffect, useState } from 'react'

// API는 동일 출처의 /api 경로로 호출한다(nginx가 app으로 프록시). 호스트 주소를 코드에 두지 않는다.
export default function App() {
  const [health, setHealth] = useState('checking...')

  useEffect(() => {
    fetch('/api/health')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => setHealth(d.status))
      .catch((e) => setHealth(`error: ${e}`))
  }, [])

  return (
    <main>
      <h1>nesume</h1>
      <p>API health: {health}</p>
    </main>
  )
}
