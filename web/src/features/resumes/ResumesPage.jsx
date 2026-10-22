import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { resumesApi } from './api.js'
import './resumes.css'

export default function ResumesPage() {
  const [items, setItems] = useState([])
  const [title, setTitle] = useState('')
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    resumesApi
      .list()
      .then((data) => {
        setItems(data)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }, [])

  useEffect(load, [load])

  const create = async (e) => {
    e.preventDefault()
    if (!title.trim()) return
    try {
      await resumesApi.create({ title: title.trim() })
      setTitle('')
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section>
      <h1>자소서</h1>
      <form className="row" onSubmit={create}>
        <input
          placeholder="새 자소서 제목 (예: 네이버 백엔드)"
          value={title}
          maxLength={200}
          onChange={(e) => setTitle(e.target.value)}
        />
        <button type="submit" disabled={!title.trim()}>
          만들기
        </button>
      </form>
      {error && <p className="error">불러오지 못했습니다: {error}</p>}
      <ul className="list resume-list">
        {items.map((r) => (
          <li key={r.id}>
            <Link to={`/resumes/${r.id}`}>{r.title}</Link>
            <span className="muted">
              {r.status ?? '상태 없음'} · {new Date(r.updated_at).toLocaleString()}
            </span>
          </li>
        ))}
        {!error && items.length === 0 && <li className="muted">자소서가 없습니다.</li>}
      </ul>
    </section>
  )
}
