import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { experiencesApi } from './api.js'
import ExperienceForm from './ExperienceForm.jsx'
import './experiences.css'

// 경험 작성(/experiences/new)·수정(/experiences/:id/edit). 목록은 보여주지 않는다(10/28) — 저장·취소하면 목록으로
export default function ExperienceEditPage() {
  const { experienceId } = useParams()
  const navigate = useNavigate()
  const [initial, setInitial] = useState(experienceId ? null : {})
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!experienceId) return
    experiencesApi.get(experienceId).then(setInitial).catch((e) => setError(e.message))
  }, [experienceId])

  const save = async (data) => {
    try {
      if (experienceId) await experiencesApi.update(experienceId, data)
      else await experiencesApi.create(data)
      navigate('/experiences')
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <section>
      <h1>{experienceId ? '경험 수정' : '경험 추가'}</h1>
      {error && <p className="error">{error}</p>}
      {initial === null && !error && <p className="muted">불러오는 중...</p>}
      {initial !== null && (
        <ExperienceForm key={experienceId ?? 'new'} initial={experienceId ? initial : undefined}
          onSubmit={save} onCancel={() => navigate('/experiences')} />
      )}
    </section>
  )
}
