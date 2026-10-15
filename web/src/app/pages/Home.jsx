import { useEffect, useState } from 'react'
import { api } from '../api/client.js'

export default function Home() {
  const [health, setHealth] = useState('checking...')

  useEffect(() => {
    const ctrl = new AbortController()
    api
      .get('/health', { signal: ctrl.signal })
      .then((d) => setHealth(d.status))
      .catch((e) => e.name !== 'AbortError' && setHealth(`error: ${e.message}`))
    return () => ctrl.abort()
  }, [])

  return (
    <section>
      <h1>nesume</h1>
      <p>API health: {health}</p>
    </section>
  )
}
