import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { resumesApi } from './api.js'
import QuestionEditor from './QuestionEditor.jsx'
import './resumes.css'

export default function ResumeDetailPage() {
  const { resumeId } = useParams()
  const navigate = useNavigate()
  const [resume, setResume] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [newQuestion, setNewQuestion] = useState({ title: '', char_limit: '' })
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    resumesApi
      .get(resumeId)
      .then((data) => {
        setResume(data)
        setError(null)
        setSelectedId((cur) => cur ?? data.questions[0]?.id ?? null)
      })
      .catch((e) => setError(e.status === 404 ? '자소서를 찾을 수 없습니다.' : e.message))
  }, [resumeId])

  useEffect(load, [load])

  const saveMeta = async (field, value) => {
    try {
      setResume(await resumesApi.update(resumeId, { [field]: value || null }).then((r) => ({ ...resume, ...r })))
    } catch (e) {
      setError(e.message)
    }
  }

  const addQuestion = async (e) => {
    e.preventDefault()
    const payload = { title: newQuestion.title.trim() }
    if (newQuestion.char_limit) payload.char_limit = Number(newQuestion.char_limit)
    try {
      const q = await resumesApi.createQuestion(resumeId, payload)
      setNewQuestion({ title: '', char_limit: '' })
      setSelectedId(q.id)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const removeQuestion = async (qid) => {
    if (!window.confirm('문항을 삭제할까요? 30일 후 완전히 삭제됩니다.')) return
    await resumesApi.removeQuestion(resumeId, qid)
    setSelectedId(null)
    load()
  }

  const removeResume = async () => {
    if (!window.confirm('자소서를 삭제할까요? 30일 후 완전히 삭제됩니다.')) return
    await resumesApi.remove(resumeId)
    navigate('/resumes')
  }

  if (error && !resume) return <p className="error">{error}</p>
  if (!resume) return <p className="muted">불러오는 중...</p>

  const selected = resume.questions.find((q) => q.id === selectedId)

  return (
    <section>
      <div className="row">
        <input
          className="title-input"
          defaultValue={resume.title}
          maxLength={200}
          onBlur={(e) => e.target.value.trim() && e.target.value !== resume.title && saveMeta('title', e.target.value.trim())}
          aria-label="자소서 제목"
        />
        <input
          className="status-input"
          defaultValue={resume.status ?? ''}
          placeholder="상태"
          maxLength={20}
          onBlur={(e) => e.target.value !== (resume.status ?? '') && saveMeta('status', e.target.value.trim())}
          aria-label="상태"
        />
        <button className="secondary" onClick={removeResume}>
          삭제
        </button>
      </div>
      {error && <p className="error">{error}</p>}

      <div className="detail-grid">
        <aside>
          <h2>문항</h2>
          <ul className="question-list">
            {resume.questions.map((q) => (
              <li key={q.id} className={q.id === selectedId ? 'active' : ''}>
                <button className="link" onClick={() => setSelectedId(q.id)}>
                  {q.title}
                </button>
                <span className="muted">
                  {q.latest_version ? `v${q.latest_version.version_no}` : '미작성'}
                </span>
              </li>
            ))}
          </ul>
          <form className="stack" onSubmit={addQuestion}>
            <input
              placeholder="문항 제목"
              value={newQuestion.title}
              onChange={(e) => setNewQuestion({ ...newQuestion, title: e.target.value })}
            />
            <input
              type="number"
              min="1"
              placeholder="글자 수 제한(선택)"
              value={newQuestion.char_limit}
              onChange={(e) => setNewQuestion({ ...newQuestion, char_limit: e.target.value })}
            />
            <button type="submit" disabled={!newQuestion.title.trim()}>
              문항 추가
            </button>
          </form>
        </aside>
        <div>
          {selected ? (
            <QuestionEditor
              key={selected.id}
              resumeId={resumeId}
              question={selected}
              onSaved={load}
              onDelete={() => removeQuestion(selected.id)}
            />
          ) : (
            <p className="muted">문항을 추가하거나 선택하세요.</p>
          )}
        </div>
      </div>
    </section>
  )
}
