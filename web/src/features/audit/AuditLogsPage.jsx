import { useCallback, useEffect, useState } from 'react'
import { auditApi, errorText } from './api.js'
import './audit.css'

// AI 사용 기록(B11 화면, 10/29): 누가·언제·어떤 기능으로 무엇을 물었고 어떻게 판정됐는지. 운영자(MFA) 전용.
// 질문·답변은 개인정보를 가린 형태로만 저장된다(spec 10.1). 답변 기록은 감사 로그 칸 추가·A8 연결 후 표시
const PAGE = 50
const DECISION = { allow: '허용', mask: '가림', block: '차단' }

const fmt = (iso) => new Date(iso).toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'medium' })
const dayStart = (d) => (d ? new Date(`${d}T00:00:00`).toISOString() : undefined)
const dayEnd = (d) => (d ? new Date(new Date(`${d}T00:00:00`).getTime() + 86400000).toISOString() : undefined)

function Row({ log, email }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="aud-row">
      <div className="aud-meta">
        <span className="aud-who">{email ?? `${log.user_id.slice(0, 8)}…`}</span>
        <span className="muted">{log.role}</span>
        <span className="muted">· {fmt(log.timestamp)}</span>
        <span className="muted">· {log.feature}</span>
        <span className={`aud-pill ${log.decision}`}>{DECISION[log.decision] ?? log.decision}</span>
        {log.query_type && <span className="muted">· {log.query_type}</span>}
        {log.flags.length > 0 && <span className="muted">· {log.flags.join(', ')}</span>}
        {log.is_test && <span className="muted">· 평가</span>}
      </div>
      <dl className="aud-qa">
        <dt>질문</dt>
        <dd className={open ? '' : 'clip'}>{log.query_masked || <span className="muted">(없음)</span>}</dd>
        <dt>답변</dt>
        <dd className={open ? '' : 'clip'}>
          {log.response_masked ?? <span className="muted">{log.decision === 'block' ? '(차단되어 답변 없음)' : '(기록 없음)'}</span>}
        </dd>
      </dl>
      <button type="button" className="link" onClick={() => setOpen((o) => !o)}>{open ? '접기' : '전체 보기'}</button>
    </li>
  )
}

export default function AuditLogsPage() {
  const [f, setF] = useState({ from: '', to: '', email: '', feature: '', decision: '', includeTest: false })
  const [applied, setApplied] = useState(f)
  const [logs, setLogs] = useState(null)
  const [emails, setEmails] = useState({})
  const [more, setMore] = useState(false)
  const [error, setError] = useState(null)

  const fetchPage = useCallback(async (q, offset) => {
    let userId
    if (q.email.trim()) {
      userId = (await auditApi.lookup(q.email.trim())).user_id
      if (!userId) return { rows: [], noUser: true }
    }
    const rows = await auditApi.list({
      from: dayStart(q.from), to: dayEnd(q.to), user_id: userId, feature: q.feature.trim(),
      decision: q.decision, is_test: q.includeTest ? undefined : false, limit: PAGE, offset,
    })
    return { rows }
  }, [])

  const load = useCallback(async (q, append = false) => {
    try {
      const { rows, noUser } = await fetchPage(q, append ? logs?.length ?? 0 : 0)
      const next = append ? [...(logs ?? []), ...rows] : rows
      setLogs(next)
      setMore(rows.length === PAGE)
      setError(noUser ? '해당 이메일의 사용자가 없습니다.' : null)
      const missing = [...new Set(rows.map((r) => r.user_id))].filter((id) => !(id in emails))
      if (missing.length) {
        const found = await auditApi.emails(missing.slice(0, 100)).catch(() => ({}))
        setEmails((cur) => ({ ...cur, ...found }))
      }
    } catch (e) {
      setError(errorText(e))
      if (!append) setLogs([])
    }
  }, [fetchPage, logs, emails])

  // 조건을 '조회'로 적용할 때만 다시 불러온다(load는 매번 바뀌므로 의존성에서 뺀다)
  useEffect(() => {
    load(applied)
  }, [applied])

  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  return (
    <section>
      <h1>AI 사용 기록</h1>
      <p className="muted">AI 기능을 쓴 기록입니다. 질문·답변의 개인정보는 가려서 저장됩니다. 운영자(MFA)만 볼 수 있습니다.</p>

      <form className="aud-filters" onSubmit={(e) => { e.preventDefault(); setApplied(f) }}>
        <input type="date" value={f.from} onChange={set('from')} aria-label="시작일" />
        <span className="muted">~</span>
        <input type="date" value={f.to} onChange={set('to')} aria-label="종료일" />
        <input type="email" placeholder="사용자 이메일" value={f.email} onChange={set('email')} aria-label="사용자 이메일" />
        <input placeholder="기능(예: writing.proofread)" value={f.feature} onChange={set('feature')} aria-label="기능" />
        <select value={f.decision} onChange={set('decision')} aria-label="판정">
          <option value="">판정 전체</option>
          {Object.entries(DECISION).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <label><input type="checkbox" checked={f.includeTest} onChange={set('includeTest')} /> 평가 트래픽 포함</label>
        <button type="submit">조회</button>
      </form>

      {error && <p className="error">{error}</p>}
      {logs === null && !error && <p className="muted">불러오는 중...</p>}
      {logs?.length === 0 && !error && <div className="card aud-card"><p className="muted">기록이 없습니다.</p></div>}
      {logs?.length > 0 && (
        <div className="card aud-card">
          <ul className="aud-list">
            {logs.map((l) => <Row key={l.request_id} log={l} email={emails[l.user_id]} />)}
          </ul>
          {more && (
            <div className="aud-more">
              <button type="button" className="secondary" onClick={() => load(applied, true)}>더 보기</button>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
