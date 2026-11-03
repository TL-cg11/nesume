import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { resumesApi } from '../resumes/api.js'
import { ANSWER_MAX, FEEDBACK_KEYS, MAIN, interviewApi } from './api.js'
import './interview.css'

// B13 모의 면접(11/2, part2_guide 4.72): 자소서를 고르면 무작위 면접관(실무·인성·압박, 면접 동안 유지)이
// 대화로 면접을 진행한다. 주 질문마다 꼬리 질문 최대 2개. 끝나면 종합 피드백과 자소서 기반 예상 질문을 옆에 보여 준다.
// 연습 기록은 본인만 보고 멘토 공유에 들어가지 않는다
const when = (iso) =>
  new Date(iso).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

const notice = (out, what) =>
  out.llm_unavailable ? `AI 면접관에 연결하지 못했습니다. ${what}`
    : out.blocked_reason ? `보안 정책에 따라 처리할 수 없는 내용입니다. ${what}` : null

function Feedback({ session, onRetry, busy }) {
  if (session.answers === 0) return <p className="muted">답변이 없어 피드백이 없습니다.</p>
  if (!session.feedback) {
    return (
      <div className="stack">
        <p className="muted">피드백을 아직 받지 못했습니다.</p>
        <button type="button" onClick={onRetry} disabled={busy}>{busy ? '받는 중…' : '피드백 다시 받기'}</button>
      </div>
    )
  }
  return (
    <dl className="iv-feedback">
      {FEEDBACK_KEYS.filter((k) => session.feedback[k]).map((k) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{session.feedback[k]}</dd>
        </div>
      ))}
    </dl>
  )
}

function Chat({ resumeId, session, onChange }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(null) // 'answer' | 'finish' | 'feedback'
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)
  const end = useRef(null)
  const active = session.status === 'active'

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest' })
  }, [session.messages.length, busy])

  const run = async (kind, call, what) => {
    setBusy(kind)
    setError(null)
    setInfo(null)
    try {
      const out = await call()
      if (out.session) onChange(out.session)
      setInfo(notice(out, what))
      return out
    } catch (err) {
      setError(err.message)
      return null
    } finally {
      setBusy(null)
    }
  }

  const send = async (e) => {
    e?.preventDefault()
    if (!text.trim() || busy) return
    const out = await run('answer', () => interviewApi.answer(resumeId, session.id, text), '같은 답변을 다시 보내 주세요.')
    if (out && !out.llm_unavailable && !out.blocked_reason) setText('') // 실패하면 쓴 답변을 남겨 둔다
  }

  const finish = () => {
    if (!window.confirm('면접을 끝낼까요? 지금까지의 답변으로 피드백을 받습니다.')) return
    run('finish', () => interviewApi.finish(resumeId, session.id), '‘피드백 다시 받기’를 눌러 주세요.')
  }

  const onKey = (e) => {
    // Enter 보내기, Shift+Enter 줄바꿈. 한글 조합 중 Enter는 무시
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) send(e)
  }

  return (
    <div className="iv-main">
      <div className="card iv-chat">
        <div className="iv-chat-head">
          <strong className="grow">
            {active ? `주 질문 ${session.main_no}/${session.main_count}` : `면접 종료 · ${session.persona_label ?? ''}`}
          </strong>
          {active && (
            <button type="button" className="secondary" onClick={finish} disabled={!!busy}>
              {busy === 'finish' ? '마무리 중…' : '면접 종료'}
            </button>
          )}
        </div>
        <ol className="iv-messages" aria-live="polite">
          {session.messages.map((m) => (
            <li key={m.id} className={`iv-msg ${m.role}`}>
              {m.role === 'interviewer' && (
                <span className="iv-who">면접관{m.kind === 'follow_up' && <span className="iv-tag">꼬리 질문</span>}</span>
              )}
              <p>{m.body}</p>
            </li>
          ))}
          {busy === 'answer' && <li className="iv-msg candidate pending"><p>{text}</p></li>}
          {(busy === 'answer' || busy === 'finish') && (
            <li className="iv-msg interviewer"><p className="muted">면접관이 생각하는 중…</p></li>
          )}
          <li ref={end} aria-hidden="true" />
        </ol>
        {active ? (
          <form className="iv-input" onSubmit={send}>
            <textarea value={text} onChange={(e) => setText(e.target.value.slice(0, ANSWER_MAX))} onKeyDown={onKey}
              rows={3} placeholder="답변을 입력하세요 (Enter 보내기, Shift+Enter 줄바꿈)" aria-label="답변"
              disabled={!!busy} />
            <div className="row">
              <span className="muted grow">
                {text.length.toLocaleString()} / {ANSWER_MAX.toLocaleString()}자 · 주민번호·계좌번호 등은 입력할 수 없습니다
              </span>
              <button type="submit" disabled={!!busy || !text.trim()}>보내기</button>
            </div>
          </form>
        ) : (
          <p className="muted iv-ended">면접이 끝났습니다. 옆에서 피드백을 확인하세요.</p>
        )}
        {error && <p className="error">{error}</p>}
        {info && <p className="notice">{info}</p>}
      </div>
      {!active && (
        <aside className="card iv-result">
          <h2>피드백</h2>
          {session.persona_label && <p className="muted">이번 면접관: {session.persona_label}</p>}
          <Feedback session={session} busy={busy === 'feedback'}
            onRetry={() => run('feedback', () => interviewApi.feedback(resumeId, session.id), '잠시 후 다시 시도해 주세요.')} />
          {session.expected_questions.length > 0 && (
            <>
              <h2>예상 면접 질문</h2>
              <p className="muted">이번 면접과 별개로 자기소개서·경험에서 뽑은 질문입니다.</p>
              <ol className="iv-expected">
                {session.expected_questions.map((q, i) => <li key={i}>{q}</li>)}
              </ol>
            </>
          )}
        </aside>
      )}
    </div>
  )
}

export default function InterviewPage() {
  const [params, setParams] = useSearchParams()
  const resumeId = params.get('resume') ?? ''
  const sessionId = params.get('session') ?? ''
  const [resumes, setResumes] = useState(null)
  const [mainCount, setMainCount] = useState(MAIN.default)
  const [sessions, setSessions] = useState(null)
  const [session, setSession] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)

  const go = (rid, sid) => setParams({ ...(rid && { resume: rid }), ...(sid && { session: sid }) })

  useEffect(() => {
    resumesApi.list().then(setResumes).catch((e) => setError(e.message))
  }, [])

  const loadList = useCallback(() => {
    if (!resumeId) return setSessions(null)
    interviewApi.list(resumeId).then(setSessions).catch((e) => setError(e.message))
  }, [resumeId])
  useEffect(loadList, [loadList])

  useEffect(() => {
    if (!resumeId || !sessionId) return setSession(null)
    if (session?.id === sessionId) return
    let alive = true
    interviewApi.get(resumeId, sessionId).then((s) => alive && setSession(s)).catch((e) => alive && setError(e.message))
    return () => { alive = false }
  }, [resumeId, sessionId]) // eslint-disable-line react-hooks/exhaustive-deps

  const start = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setInfo(null)
    try {
      const out = await interviewApi.start(resumeId, mainCount)
      if (out.session) {
        setSession(out.session)
        go(resumeId, out.session.id)
        loadList()
      } else setInfo(notice(out, '잠시 후 다시 시도해 주세요.'))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const changed = (s) => {
    const wasActive = session?.status === 'active'
    setSession(s)
    if (wasActive !== (s.status === 'active') || s.answers !== session?.answers) loadList()
  }

  const remove = async (s) => {
    if (!window.confirm('이 면접 기록을 삭제할까요? 되돌릴 수 없습니다.')) return
    try {
      await interviewApi.remove(resumeId, s.id)
      setSessions((xs) => xs.filter((x) => x.id !== s.id))
      if (sessionId === s.id) go(resumeId)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section className="iv-page">
      <h1>면접 연습</h1>
      <form className="card iv-setup" onSubmit={start}>
        <label>
          자기소개서
          <select value={resumeId} onChange={(e) => go(e.target.value)} aria-label="자기소개서">
            <option value="">자기소개서를 고르세요</option>
            {resumes?.map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}
          </select>
        </label>
        <label className="iv-count">
          주 질문 수
          <input type="number" min={MAIN.min} max={MAIN.max} value={mainCount}
            onChange={(e) => setMainCount(Math.min(MAIN.max, Math.max(MAIN.min, Number(e.target.value) || MAIN.min)))} />
        </label>
        <button type="submit" disabled={!resumeId || busy}>{busy ? '면접관 입장 중…' : '모의 면접 시작'}</button>
        <p className="muted iv-note">
          면접관은 매번 무작위로 정해지고, 답변에 따라 꼬리 질문(주 질문마다 최대 2개)을 합니다. 고른 자기소개서와 문항에 연결한
          경험만 참고하며, 기록은 본인만 볼 수 있고 멘토 공유에 포함되지 않습니다.
          {resumeId && <> · <Link to={`/resumes/${resumeId}`}>자기소개서 열기</Link></>}
        </p>
      </form>
      {error && <p className="error">{error}</p>}
      {info && <p className="notice">{info}</p>}
      {resumes?.length === 0 && (
        <div className="card"><p>먼저 <Link to="/resumes">자기소개서</Link>를 작성해 주세요.</p></div>
      )}
      {resumeId && (
        <div className={`iv-body${session ? '' : ' empty'}`}>
          <div className="card iv-sessions">
            <h2>지난 면접</h2>
            {sessions === null && <p className="muted">불러오는 중...</p>}
            {sessions?.length === 0 && <p className="muted">아직 면접 기록이 없습니다.</p>}
            <ul className="list">
              {sessions?.map((s) => (
                <li key={s.id} className={`iv-s${s.id === sessionId ? ' on' : ''}`}>
                  <button type="button" className="link iv-s-main" onClick={() => go(resumeId, s.id)}>
                    <span>{when(s.created_at)}</span>
                    <span className="muted">
                      {s.status === 'active' ? '진행 중' : `완료 · ${s.persona_label}`} · 답변 {s.answers}개
                    </span>
                  </button>
                  <button type="button" className="iv-del" onClick={() => remove(s)} aria-label="면접 기록 삭제" title="삭제">×</button>
                </li>
              ))}
            </ul>
          </div>
          {session ? (
            <Chat key={session.id} resumeId={resumeId} session={session} onChange={changed} />
          ) : (
            <div className="card iv-placeholder">
              <p className="muted">‘모의 면접 시작’을 누르거나 지난 면접을 고르세요.</p>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
