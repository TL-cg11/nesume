import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { experiencesApi } from './api.js'
import { period } from './summary.js'
import { TYPES, normalizeType } from './templates.js'
import './experiences.css'

// 경험 목록(10/28): 자소서 목록과 같은 양식 — 이름과 기간만. 상세·수정·삭제는 행을 눌러 들어간 열람 화면에서
export default function ExperiencesPage() {
  const navigate = useNavigate() // 작성·수정·열람은 별도 화면(/experiences/new, /:id, /:id/edit)
  const [all, setAll] = useState([])
  const [items, setItems] = useState(null) // null = 불러오는 중
  const [selectedTags, setSelectedTags] = useState([])
  const [type, setType] = useState('') // 유형 필터(10/28). '' = 전체. 예전 자유 입력 유형은 기타
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

  const shown = items && (type ? items.filter((e) => normalizeType(e.type) === type) : items)
  const countOf = (t) => (items ?? []).filter((e) => normalizeType(e.type) === t).length

  const toggleTag = (t) =>
    setSelectedTags((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]))

  return (
    <section>
      <div className="exp-head">
        <h1>
          경험 <span className="muted">{all.length}</span>
        </h1>
        <button onClick={() => navigate('/experiences/new')}>경험 추가</button>
      </div>
      {error && <p className="error">{error}</p>}

      {all.length > 0 && (
        <div className="exp-filter" aria-label="유형 필터">
          <span className="muted">유형</span>
          <button className={`chip ${type === '' ? 'on' : ''}`} onClick={() => setType('')}>
            전체 {items?.length ?? 0}
          </button>
          {TYPES.map((t) => (
            <button key={t} className={`chip ${type === t ? 'on' : ''}`} onClick={() => setType(t)}>
              {t} {countOf(t)}
            </button>
          ))}
        </div>
      )}

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

      {items === null && !error && <p className="muted">불러오는 중...</p>}
      {shown?.length === 0 && (
        <div className="card exp-empty">
          {selectedTags.length || type ? (
            <p>선택한 조건의 경험이 없습니다.</p>
          ) : (
            <>
              <p>아직 등록한 경험이 없습니다.</p>
              <p className="muted">오른쪽 위 ‘경험 추가’를 눌러 첫 경험을 기록하세요.</p>
            </>
          )}
        </div>
      )}
      {shown?.length > 0 && (
        <div className="card exp-list-card">
          <ul className="list exp-list">
            {shown.map((e) => (
              <li key={e.id}>
                {/* 제목 링크가 행 전체를 덮는다 → 빈 곳을 눌러도 열람 */}
                <Link to={`/experiences/${e.id}`} className="exp-title">{e.title}</Link>
                <span className="muted">{period(e) || '기간 없음'}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
