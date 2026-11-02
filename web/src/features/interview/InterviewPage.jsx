import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { resumesApi } from '../resumes/api.js'
import { ANSWER_MAX, COUNT, FEEDBACK_KEYS, TYPES, interviewApi, typeLabel } from './api.js'
import './interview.css'

// B13 면접 연습(11/2, spec 3.3, part2_guide 4.71): 자소서를 고르고 유형·개수로 예상 질문을 만든 뒤,
// 질문마다 답변을 써서 피드백(구조·구체성·일관성 + 제안)을 받는다. 연습 기록은 본인만 보고 멘토 공유에 들어가지 않는다
const when = (iso) => new Date(iso).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

function Feedback({ feedback }) {
  if (!feedback) return <p className="muted">피드백 없이 답변만 기록했습니다(AI 연결 안 됨).</p>
  return (
    <dl className="iv-feedback">
      {FEEDBACK_KEYS.filter((k) => feedback[k]).map((k) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{feedback[k]}</dd>
        </div>
      ))}
    </dl>
  )
}

function Practice({ resumeId, question, onAnswered }) {
  const [text, setText] = useState('')
  const [history, setHistory] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)

  useEffect(() => {
    let alive = true
    setHistory(null)
    setText('')
    setError(null)
    setNotice(null)
    interviewApi.answers(resumeId, question.id).then((h) => alive && setHistory(h)).catch((e) => alive && setError(e.message))
    return () => { alive = false }
  }, [resumeId, question.id])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const out = await interviewApi.answer(resumeId, question.id, text)
      if (out.blocked_reason) {
        setNotice('보안 정책에 따라 처리할 수 없는 답변입니다. 내용을 고쳐 다시 시도해 주세요.')
      } else {
        setHistory((h) => [out.answer, ...(h ?? [])])
        setText('')
        onAnswered(question.id)
        if (out.llm_unavailable) setNotice('AI에 연결하지 못해 답변만 기록했습니다.')
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const latest = history?.[0]
  return (
    <div className="card iv-practice">
      <span className="iv-type">{typeLabel(question.type)}</span>
      <h2>{question.body}</h2>
      <form onSubmit={submit} className="stack">
        <textarea value={text} onChange={(e) => setText(e.target.value.slice(0, ANSWER_MAX))} rows={7}
          placeholder="실제 면접처럼 답변을 써 보세요. 결론 → 상황 → 행동 → 결과 순서가 좋습니다." aria-label="답변" />
        <div className="row">
          <span className="muted grow">{text.length.toLocaleString()} / {ANSWER_MAX.toLocaleString()}자 · 주민번호·계좌번호 등은 입력할 수 없습니다</span>
          <button type="submit" disabled={busy || !text.trim()}>{busy ? '피드백 받는 중…' : '피드백 받기'}</button>
        </div>
      </form>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {latest && (
        <div className="iv-latest">
          <h3>최근 피드백 <span className="muted">{when(latest.created_at)}</span></h3>
          <Feedback feedback={latest.feedback} />
        </div>
      )}
      {history?.length > 0 && (
        <details className="iv-history">
          <summary>연습 기록 {history.length}회</summary>
          <ul className="list">
            {history.map((a) => (
              <li key={a.id}>
                <span className="muted">{when(a.created_at)}</span>
                <p className="iv-answer">{a.answer}</p>
                <Feedback feedback={a.feedback} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

export default function InterviewPage() {
  const [params, setParams] = useSearchParams()
  const resumeId = params.get('resume') ?? ''
  const [resumes, setResumes] = useState(null)
  const [type, setType] = useState('personality')
  const [count, setCount] = useState(COUNT.default)
  const [filter, setFilter] = useState('')
  const [questions, setQuestions] = useState(null)
  const [selected, setSelected] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)

  useEffect(() => {
    resumesApi.list().then(setResumes).catch((e) => setError(e.message))
  }, [])

  const load = useCallback(() => {
    if (!resumeId) return
    setQuestions(null)
    interviewApi.list(resumeId).then((qs) => {
      setQuestions(qs)
      setError(null)
    }).catch((e) => setError(e.message))
  }, [resumeId])
  useEffect(() => {
    setSelected(null)
    setNotice(null)
    load()
  }, [load])

  const generate = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const out = await interviewApi.generate(resumeId, type, count)
      if (out.llm_unavailable) setNotice('AI에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.')
      else if (out.blocked_reason) setNotice('보안 정책에 따라 질문을 만들 수 없습니다. 자소서 내용을 확인해 주세요.')
      else {
        setQuestions((qs) => [...out.questions, ...(qs ?? [])])
        setFilter('')
        setSelected(out.questions[0]?.id ?? null)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (q) => {
    if (!window.confirm('이 질문과 연습 기록을 삭제할까요? 되돌릴 수 없습니다.')) return
    try {
      await interviewApi.remove(resumeId, q.id)
      setQuestions((qs) => qs.filter((x) => x.id !== q.id))
      if (selected === q.id) setSelected(null)
    } catch (err) {
      setError(err.message)
    }
  }

  const answered = (qid) =>
    setQuestions((qs) => qs.map((q) => (q.id === qid ? { ...q, answer_count: q.answer_count + 1 } : q)))

  const shown = (questions ?? []).filter((q) => !filter || q.type === filter)
  const current = questions?.find((q) => q.id === selected)

  return (
    <section className="iv-page">
      <h1>면접 연습</h1>
      <form className="card iv-setup" onSubmit={generate}>
        <label>
          자기소개서
          <select value={resumeId} onChange={(e) => setParams(e.target.value ? { resume: e.target.value } : {})}
            aria-label="자기소개서">
            <option value="">자기소개서를 고르세요</option>
            {resumes?.map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}
          </select>
        </label>
        <div>
          <span className="iv-label">질문 유형</span>
          <div className="row iv-chips" role="radiogroup" aria-label="질문 유형">
            {TYPES.map((t) => (
              <button key={t.value} type="button" role="radio" aria-checked={type === t.value}
                className={`chip${type === t.value ? ' on' : ''}`} onClick={() => setType(t.value)}>
                {t.label}
              </button>
            ))}
          </div>
        </div>
        <label className="iv-count">
          개수
          <input type="number" min={COUNT.min} max={COUNT.max} value={count}
            onChange={(e) => setCount(Math.min(COUNT.max, Math.max(COUNT.min, Number(e.target.value) || COUNT.min)))} />
        </label>
        <button type="submit" disabled={!resumeId || busy}>{busy ? '만드는 중…' : '질문 만들기'}</button>
        <p className="muted iv-note">
          고른 자기소개서의 최신 내용과 문항에 연결한 경험만 참고합니다. 연습 기록은 본인만 볼 수 있고 멘토 공유에 포함되지 않습니다.
          {resumeId && <> · <Link to={`/resumes/${resumeId}`}>자기소개서 열기</Link></>}
        </p>
      </form>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {resumes?.length === 0 && (
        <div className="card"><p>먼저 <Link to="/resumes">자기소개서</Link>를 작성해 주세요.</p></div>
      )}
      {resumeId && questions === null && !error && <p className="muted">불러오는 중...</p>}
      {questions?.length === 0 && (
        <div className="card"><p className="muted">아직 만든 질문이 없습니다. 유형과 개수를 고르고 ‘질문 만들기’를 누르세요.</p></div>
      )}
      {questions?.length > 0 && (
        <div className="iv-body">
          <div className="card iv-questions">
            <div className="row iv-chips">
              {[{ value: '', label: '전체' }, ...TYPES].map((t) => (
                <button key={t.value} type="button" className={`chip${filter === t.value ? ' on' : ''}`}
                  onClick={() => setFilter(t.value)}>
                  {t.label} {(t.value ? questions.filter((q) => q.type === t.value) : questions).length}
                </button>
              ))}
            </div>
            <ul className="list">
              {shown.map((q) => (
                <li key={q.id} className={`iv-q${q.id === selected ? ' on' : ''}`}>
                  <button type="button" className="link iv-q-main" onClick={() => setSelected(q.id)}>
                    <span className="iv-type">{typeLabel(q.type)}</span>
                    <span>{q.body}</span>
                    <span className="muted">{q.answer_count > 0 ? `연습 ${q.answer_count}회` : '연습 전'}</span>
                  </button>
                  <button type="button" className="iv-del" onClick={() => remove(q)} aria-label="질문 삭제" title="삭제">×</button>
                </li>
              ))}
            </ul>
          </div>
          {current ? (
            <Practice resumeId={resumeId} question={current} onAnswered={answered} />
          ) : (
            <div className="card iv-practice"><p className="muted">왼쪽에서 질문을 고르면 답변을 연습할 수 있습니다.</p></div>
          )}
        </div>
      )}
    </section>
  )
}
