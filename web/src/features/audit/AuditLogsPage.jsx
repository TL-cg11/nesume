import { useCallback, useEffect, useState } from 'react'
import { auditApi, errorText } from './api.js'
import { BLOCK_WHEN, MASK_WHEN, STAGE, conversationName, featureText, maskedCounts, ruleText, splitMasked } from './labels.js'
import './audit.css'

// AI 사용 기록(B11 화면, 10/29): 누가·언제·어떤 기능으로 무엇을 물었고 어떻게 판정됐는지. 운영자(MFA) 전용.
// 질문·답변은 개인정보를 가린 형태로만 저장된다(spec 10.1). 11/3: 답변 기록, 가린 자리 강조, 판정 상세(4.74)
// 11/3: 같은 대화(세션)의 기록에 대화 이름을 붙이고, 누르면 그 대화만 시간순으로 모아 본다(4.77)
const PAGE = 50
const CONVERSATION_MAX = 500
const DECISION = { allow: '허용', mask: '가림', block: '차단' }

const fmt = (iso) => new Date(iso).toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'medium' })
const dayStart = (d) => (d ? new Date(`${d}T00:00:00`).toISOString() : undefined)
const dayEnd = (d) => (d ? new Date(new Date(`${d}T00:00:00`).getTime() + 86400000).toISOString() : undefined)

// 가린 자리를 강조해서 보여 준다(원래 값은 저장돼 있지 않다)
function MaskedText({ text }) {
  return splitMasked(text).map((p, i) =>
    p.masked ? <mark key={i} className="aud-masked" title={`${p.kind} 가림`}>{p.kind}</mark> : <span key={i}>{p.text}</span>,
  )
}

// 판정 상세: 어느 단계에서, 어떤 규칙으로, 무엇을 가렸는지·막았는지
function Detail({ log }) {
  const rules = [...new Set([log.rule_id, ...log.flags].filter(Boolean))]
  const counts = Object.entries(maskedCounts(log.query_masked, log.response_masked))
  if (log.decision === 'allow' && !rules.length && !counts.length) return null
  const when = log.decision === 'block' ? BLOCK_WHEN : log.decision === 'mask' ? MASK_WHEN : null
  return (
    <div className={`aud-detail ${log.decision}`}>
      {when && log.decision_stage && (
        <p><strong>{STAGE[log.decision_stage] ?? log.decision_stage}</strong> · {when[log.decision_stage] ?? ''}</p>
      )}
      {rules.length > 0 && (
        <ul className="aud-rules">
          {rules.map((r) => (
            <li key={r}>{ruleText(r)} <code className="muted">{r}</code>{r === log.rule_id && rules.length > 1 && ' · 대표 규칙'}</li>
          ))}
        </ul>
      )}
      {counts.length > 0 && (
        <p className="muted">가린 항목: {counts.map(([k, n]) => `${k} ${n}건`).join(', ')}</p>
      )}
      {log.canary_hit && <p className="error">미끼(카나리) 문서가 감지되었습니다.</p>}
    </div>
  )
}

function Row({ log, email, onConversation }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="aud-row">
      <div className="aud-meta">
        <span className="aud-who">{email ?? `${log.user_id.slice(0, 8)}…`}</span>
        <span className="muted">{log.role}</span>
        <span className="muted">· {fmt(log.timestamp)}</span>
        <span className="muted">· {featureText(log.feature)}</span>
        <span className={`aud-pill ${log.decision}`}>{DECISION[log.decision] ?? log.decision}</span>
        {log.query_type && <span className="muted">· {log.query_type}</span>}
        {log.is_test && <span className="muted">· 평가</span>}
        {onConversation && conversationName(log) && (
          <button type="button" className="aud-conv" title="이 대화의 기록만 모아 보기"
            onClick={() => onConversation(log)}>대화 {conversationName(log)}</button>
        )}
      </div>
      <dl className="aud-qa">
        <dt>질문</dt>
        <dd className={open ? '' : 'clip'}>{log.query_masked ? <MaskedText text={log.query_masked} /> : <span className="muted">(없음)</span>}</dd>
        <dt>답변</dt>
        <dd className={open ? '' : 'clip'}>
          {log.response_masked ? <MaskedText text={log.response_masked} />
            : <span className="muted">{log.decision === 'block' ? '(차단되어 답변 없음)' : '(기록 없음 — 답변 기록 이전 요청)'}</span>}
        </dd>
      </dl>
      <Detail log={log} />
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
  const [conv, setConv] = useState(null) // 모아 보는 대화: { id, name, logs }

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

  // 한 대화의 기록 전부(필터와 무관, 평가 트래픽 포함)를 시간순으로
  const openConversation = async (log) => {
    try {
      const rows = await auditApi.list({ session_id: log.session_id, limit: CONVERSATION_MAX })
      setConv({ id: log.session_id, name: conversationName(log), logs: [...rows].reverse(), more: rows.length === CONVERSATION_MAX })
      setError(null)
      window.scrollTo?.(0, 0)
    } catch (e) {
      setError(errorText(e))
    }
  }

  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  return (
    <section>
      <h1>AI 사용 기록</h1>
      <p className="muted">AI 기능을 쓴 기록입니다. 질문·답변의 개인정보는 가려서 저장됩니다. 운영자(MFA)만 볼 수 있습니다.</p>

      <form className="aud-filters" onSubmit={(e) => { e.preventDefault(); setConv(null); setApplied(f) }}>
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
      {conv && (
        <div className="card aud-card">
          <div className="aud-conv-head">
            <strong>대화 {conv.name}</strong>
            <span className="muted">기록 {conv.logs.length}건 · 시간순{conv.more ? ` (앞 ${CONVERSATION_MAX}건까지)` : ''}</span>
            <button type="button" className="secondary" onClick={() => setConv(null)}>전체 기록으로</button>
          </div>
          <ul className="aud-list">
            {conv.logs.map((l) => <Row key={l.request_id} log={l} email={emails[l.user_id]} />)}
          </ul>
        </div>
      )}
      {!conv && logs === null && !error && <p className="muted">불러오는 중...</p>}
      {!conv && logs?.length === 0 && !error && <div className="card aud-card"><p className="muted">기록이 없습니다.</p></div>}
      {!conv && logs?.length > 0 && (
        <div className="card aud-card">
          <ul className="aud-list">
            {logs.map((l) => <Row key={l.request_id} log={l} email={emails[l.user_id]} onConversation={openConversation} />)}
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
