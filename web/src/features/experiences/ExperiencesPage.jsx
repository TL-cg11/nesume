import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { experiencesApi } from './api.js'
import { period } from './summary.js'
import './experiences.css'

export default function ExperiencesPage() {
  const [all, setAll] = useState([])
  const [items, setItems] = useState([])
  const [selectedTags, setSelectedTags] = useState([])
  const navigate = useNavigate() // 작성·수정은 별도 화면(/experiences/new, /:id/edit, 10/28)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const [everything, filtered] = await Promise.all([
        experiencesApi.list(),
        selectedTags.length ? experiencesApi.list(selectedTags) : null,
      ])
      setAll(everything)
      setItems(filtered ?? everything)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [selectedTags])

  useEffect(() => {
    load()
  }, [load])

  const allTags = useMemo(() => [...new Set(all.flatMap((e) => e.tags))].sort(), [all])

  const toggleTag = (t) =>
    setSelectedTags((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]))

  const remove = async (e) => {
    if (!window.confirm(`'${e.title}'을(를) 삭제할까요? 30일 후 완전히 삭제됩니다.`)) return
    await experiencesApi.remove(e.id)
    load()
  }

  return (
    <section>
      <div className="row">
        <h1 className="grow">경험</h1>
        <button onClick={() => navigate('/experiences/new')}>경험 추가</button>
      </div>
      {error && <p className="error">{error}</p>}

      {allTags.length > 0 && (
        <div className="exp-filter" aria-label="태그 필터 (하나라도 포함)">
          <span className="muted">태그</span>
          {allTags.map((t) => (
            <button key={t} className={`chip ${selectedTags.includes(t) ? 'on' : ''}`} onClick={() => toggleTag(t)}>
              {t}
            </button>
          ))}
          {selectedTags.length > 0 && (
            <button className="secondary" onClick={() => setSelectedTags([])}>
              필터 해제
            </button>
          )}
        </div>
      )}

      <ul className="list exp-list">
        {items.map((e) => (
          <li key={e.id}>
            <div className="head">
              <strong>{e.title}</strong>
              <span className="muted">
                {e.type}
                {e.role && ` · ${e.role}`}
                {period(e) && ` · ${period(e)}`}
              </span>
              <button className="secondary" onClick={() => navigate(`/experiences/${e.id}/edit`)}>
                수정
              </button>
              <button className="danger" onClick={() => remove(e)}>
                삭제
              </button>
            </div>
            {e.outcome && <p>{e.outcome}</p>}
            {e.tech_stack.length > 0 && <p className="muted">사용 기술: {e.tech_stack.join(', ')}</p>}
            {e.tags.length > 0 && <p className="muted">#{e.tags.join(' #')}</p>}
          </li>
        ))}
        {!error && items.length === 0 && <li className="muted">경험이 없습니다.</li>}
      </ul>
    </section>
  )
}
