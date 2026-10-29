import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
import { resumesApi } from './api.js'
import QuestionEditor from './QuestionEditor.jsx'
import SharePanel from './SharePanel.jsx'
import { BODY_MAX, DEFAULT_LIMIT, LIMIT_STEP, TITLE_MAX, clampLimit } from './limits.js'
import './resumes.css'

// 자소서 상태(발표 시안, 4.54). 서버 schemas.RESUME_STATUSES와 같다
const RESUME_STATUSES = ['작성 중', '검토 중', '완료']

const TABS = [
  { id: 'write', label: '자기소개서 작성' },
  { id: 'versions', label: '버전 관리 및 비교' },
  { id: 'share', label: '멘토 공유' },
]

export default function ResumeDetailPage() {
  const { resumeId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  // 탭(10/29): 작성 | 버전 관리·비교 | 멘토 공유. 주소(?tab=)에 남겨 새로고침·뒤로 가기에도 유지
  const [params, setParams] = useSearchParams()
  const tab = TABS.some((t) => t.id === params.get('tab')) ? params.get('tab') : 'write'
  const tabsRef = useRef(null)
  // 탭을 바꿀 때 스크롤 통일(10/29): 탭 줄보다 아래로 내려가 있었다면 세 탭 모두 탭 줄이 맨 위에 오게 올린다.
  // (짧은 공유 탭만 페이지가 줄어 저절로 올라가던 차이를 없앤다) 탭 줄이 보이는 위치면 그대로 둔다
  const goTab = (id) => {
    setParams(id === 'write' ? {} : { tab: id }, { replace: true })
    const el = tabsRef.current
    // 새 탭이 그려진 뒤에 맞춘다(그리기 전에 옮기면 짧은 탭에서 위치가 어긋남)
    if (el && el.getBoundingClientRect().top < 0) requestAnimationFrame(() => el.scrollIntoView({ block: 'start' }))
  }
  const [resume, setResume] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [newQuestion, setNewQuestion] = useState({ title: '', char_limit: String(DEFAULT_LIMIT) })
  const [adding, setAdding] = useState(false) // 문항 추가: 버튼을 눌러야 입력칸이 열린다(10/29)
  const [error, setError] = useState(null)
  const [shareRev, setShareRev] = useState(0) // 공유가 바뀌면 버전 태그를 다시 불러온다

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
    payload.char_limit = clampLimit(newQuestion.char_limit) // 비우면 기본 1,000자, 최대 10,000자
    try {
      const q = await resumesApi.createQuestion(resumeId, payload)
      setNewQuestion({ title: '', char_limit: String(DEFAULT_LIMIT) })
      setAdding(false)
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
          // '자기소개서 작성' 버튼(목록·홈)으로 막 만든 경우: 제목 칸을 선택해 두어 바로 입력하게 한다
          autoFocus={location.state?.focusTitle}
          onFocus={(e) => location.state?.focusTitle && e.target.select()}
          maxLength={200}
          onBlur={(e) => e.target.value.trim() && e.target.value !== resume.title && saveMeta('title', e.target.value.trim())}
          aria-label="자소서 제목"
        />
        <select
          className="status-input"
          value={resume.status ?? ''}
          onChange={(e) => saveMeta('status', e.target.value)}
          aria-label="상태"
        >
          <option value="">상태 없음</option>
          {RESUME_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button className="danger" onClick={removeResume}>
          삭제
        </button>
      </div>
      {error && <p className="error">{error}</p>}

      <div className="resume-tabs" role="tablist" aria-label="자소서 기능" ref={tabsRef}>
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id}
            className={tab === t.id ? 'on' : undefined} onClick={() => goTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'share' && (
        <SharePanel
          resumeId={resumeId}
          onChanged={() => {
            setShareRev((n) => n + 1)
            load()
          }}
        />
      )}

      {/* 공유 탭에서도 편집 화면은 그대로 둔 채 가린다 — 작성 중인 글이 사라지지 않게 */}
      <div className="detail-grid" hidden={tab === 'share'}>
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
          {/* noValidate: 브라우저 숫자칸 검사(step 기준값)로 1,000·950 같은 값이 막히지 않게. 범위는 clampLimit이 맞춘다 */}
          {tab === 'write' && !adding && (
            <button type="button" className="add-question-btn" onClick={() => setAdding(true)}>+ 문항 추가</button>
          )}
          {tab === 'write' && adding && (
          <form className="stack" onSubmit={addQuestion} noValidate>
            <input
              autoFocus
              placeholder="문항 제목"
              maxLength={TITLE_MAX}
              value={newQuestion.title}
              onChange={(e) => setNewQuestion({ ...newQuestion, title: e.target.value })}
            />
            <label className="muted limit-field">
              글자 수 제한
              <input
                type="number"
                min="0"
                max={BODY_MAX}
                step={LIMIT_STEP}
                value={newQuestion.char_limit}
                onChange={(e) => setNewQuestion({ ...newQuestion, char_limit: e.target.value })}
                onBlur={(e) => setNewQuestion({ ...newQuestion, char_limit: String(clampLimit(e.target.value)) })}
                aria-label="글자 수 제한"
              />
              자 (최대 {BODY_MAX.toLocaleString()}자)
            </label>
            <div className="row">
              <button type="submit" disabled={!newQuestion.title.trim()}>
                추가
              </button>
              <button type="button" className="secondary" onClick={() => setAdding(false)}>
                취소
              </button>
            </div>
          </form>
          )}
        </aside>
        <div>
          {selected ? (
            <QuestionEditor
              key={selected.id}
              resumeId={resumeId}
              question={selected}
              onSaved={load}
              onDelete={() => removeQuestion(selected.id)}
              shareRev={shareRev}
              tab={tab === 'versions' ? 'versions' : 'write'}
              onGoWrite={() => goTab('write')}
            />
          ) : (
            <p className="muted">문항을 추가하거나 선택하세요.</p>
          )}
        </div>
      </div>
    </section>
  )
}
