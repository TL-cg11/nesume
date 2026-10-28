import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { resumesApi } from './api.js'
import { shortDate } from './ShareTags.jsx'
import './resumes.css'

const MAX_RESUMES = 50 // 서버 MAX_RESUMES_PER_USER와 같다(4.56). 넘으면 서버가 안내 문구로 거부
const UNTITLED = '제목 없는 자기소개서' // 작성 버튼으로 바로 만들 때의 제목. 상세 화면에서 바꾼다

export default function ResumesPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState(null) // null = 불러오는 중
  const [creating, setCreating] = useState(false)
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

  // 작성 버튼: 바로 만들고 상세(편집) 화면으로. 제목 칸을 선택해 두어 곧바로 바꿀 수 있게 한다(10/28 결정)
  const create = async () => {
    setCreating(true)
    try {
      const r = await resumesApi.create({ title: UNTITLED })
      navigate(`/resumes/${r.id}`, { state: { focusTitle: true } })
    } catch (err) {
      setError(err.message)
      setCreating(false)
    }
  }

  const full = (items?.length ?? 0) >= MAX_RESUMES

  return (
    <section>
      <div className="resume-head">
        <h1>
          자소서 <span className="muted">{items?.length ?? 0}/{MAX_RESUMES}</span>
        </h1>
        <button onClick={create} disabled={creating || items === null || full}
          title={full ? `자기소개서는 ${MAX_RESUMES}개까지 만들 수 있습니다` : undefined}>
          {creating ? '만드는 중…' : '자소서 작성'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {items === null && !error && <p className="muted">불러오는 중...</p>}
      {items?.length === 0 && (
        <div className="card resume-empty">
          <p>아직 작성한 자기소개서가 없습니다.</p>
          <p className="muted">오른쪽 위 ‘자소서 작성’을 눌러 첫 자기소개서를 시작하세요.</p>
        </div>
      )}
      {items?.length > 0 && (
        <div className="card resume-list-card">
          <ul className="list resume-list">
            {items.map((r) => (
              <li key={r.id}>
                <Link to={`/resumes/${r.id}`}>{r.title}</Link>
                <span className="muted">
                  {r.status ?? '상태 없음'} · {new Date(r.updated_at).toLocaleString()}
                </span>
                {r.share_summary && (
                  <span className="share-summary">
                    <span className="share-tag-mark">공유 중</span>
                    {r.share_summary.active_count}명 · 가장 빠른 종료 {shortDate(r.share_summary.earliest_end_date)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
