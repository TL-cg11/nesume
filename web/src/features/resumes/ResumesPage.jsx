import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { resumesApi } from './api.js'
import { shortDate } from './ShareTags.jsx'
import './resumes.css'

const MAX_RESUMES = 50 // 서버 MAX_RESUMES_PER_USER와 같다(4.56). 넘으면 서버가 안내 문구로 거부

// 상태 '완료'인 자소서 이름 아래 추천 공고 3개(제목·직무, 10/29). 추천이 없거나 아직 연결 전이면 '준비 중' 한 줄
function Recommendations({ resumeId }) {
  const [items, setItems] = useState(undefined) // undefined = 불러오는 중, null = 준비 중
  useEffect(() => {
    const ctrl = new AbortController()
    resumesApi
      .recommendFor(resumeId, ctrl.signal)
      .then((r) => setItems(r.cold_start || !r.items.length ? null : r.items.slice(0, 3)))
      .catch((e) => e.name !== 'AbortError' && setItems(null))
    return () => ctrl.abort()
  }, [resumeId])

  if (items === undefined) return <p className="resume-recs muted">추천 공고 불러오는 중...</p>
  if (items === null) return <p className="resume-recs muted">추천 공고 준비 중</p>
  return (
    <ul className="resume-recs">
      {items.map((r) => (
        <li key={r.posting_id}>
          <span className="resume-recs-mark">추천</span>
          {[r.posting?.title, r.posting?.job_name].filter(Boolean).join(' · ') || '공고 정보 없음'}
        </li>
      ))}
    </ul>
  )
}

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
      const r = await resumesApi.createUntitled()
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
          {creating ? '만드는 중…' : '자기소개서 작성'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {items === null && !error && <p className="muted">불러오는 중...</p>}
      {items?.length === 0 && (
        <div className="card resume-empty">
          <p>아직 작성한 자기소개서가 없습니다.</p>
          <p className="muted">오른쪽 위 ‘자기소개서 작성’을 눌러 첫 자기소개서를 시작하세요.</p>
        </div>
      )}
      {items?.length > 0 && (
        <div className="card resume-list-card">
          <ul className="list resume-list">
            {items.map((r) => (
              <li key={r.id}>
                <div className="resume-main">
                  <Link to={`/resumes/${r.id}`}>{r.title}</Link>
                  {r.status === '완료' && <Recommendations resumeId={r.id} />}
                </div>
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
