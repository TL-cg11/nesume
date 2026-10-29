import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { experiencesApi } from './api.js'
import { period } from './summary.js'
import { TEMPLATES, normalizeType } from './templates.js'
import './experiences.css'

// 경험 열람(/experiences/:id, 10/28). 저장한 항목을 유형별 칸 이름으로 보여주고, 수정·삭제로 이어진다
export default function ExperienceDetailPage() {
  const { experienceId } = useParams()
  const navigate = useNavigate()
  const [e, setE] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    experiencesApi.get(experienceId).then(setE).catch((err) => setError(err.message))
  }, [experienceId])

  const remove = async () => {
    if (!window.confirm(`'${e.title}'을(를) 삭제할까요? 30일 후 완전히 삭제됩니다.`)) return
    try {
      await experiencesApi.remove(e.id)
      navigate('/experiences')
    } catch (err) {
      setError(err.message)
    }
  }

  if (error) return <p className="error">{error}</p>
  if (!e) return <p className="muted">불러오는 중...</p>

  const t = TEMPLATES[normalizeType(e.type)]
  const rows = [
    [t.period === 'single' ? '수상일' : '기간', period(e)],
    [t.role.label, e.role],
    ['사용 기술', e.tech_stack.join(', ')],
    [t.outcome.label, e.outcome],
    [t.detail.label, e.detail],
    ['태그', e.tags.length ? `#${e.tags.join(' #')}` : ''],
  ].filter(([, v]) => v)

  return (
    <section>
      <div className="exp-detail-head">
        <div>
          <span className="exp-type">{e.type}</span>
          <h1>{e.title}</h1>
        </div>
        <div className="row">
          <button className="secondary" onClick={() => navigate('/experiences')}>목록</button>
          <button className="secondary" onClick={() => navigate(`/experiences/${e.id}/edit`)}>수정</button>
          <button className="danger" onClick={remove}>삭제</button>
        </div>
      </div>
      <dl className="card exp-detail">
        {rows.map(([k, v]) => (
          <div key={k} className="exp-detail-row">
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
        {rows.length === 0 && <p className="muted">제목 외에 입력한 내용이 없습니다.</p>}
      </dl>
    </section>
  )
}
