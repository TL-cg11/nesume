import { useCallback, useEffect, useState } from 'react'
import { BLOCK_REASON_LABEL, errorText, sessionsApi } from './api.js'
import './admin.css'

// D16 세션 차단(운영자 MFA 전용). 카나리 적중·탈취 임계치로 자동 차단된 세션과 운영자가 수동 차단한 세션이 한 목록에 보인다.
// 차단 중인 세션의 LLM 요청은 429 로 거부된다. 자동 차단(카나리)은 만료가 없으므로 여기서 풀어야 다시 쓸 수 있다.
const REFRESH_MS = 30_000

const fmt = (iso) => (iso ? new Date(iso).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-')

export default function AdminSessionsPage() {
  const [showHistory, setShowHistory] = useState(false)
  const [items, setItems] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(null)
  const [form, setForm] = useState({ sessionId: '', note: '', minutes: '' })

  const load = useCallback(async (history, signal) => {
    try {
      const list = await sessionsApi.blocked(!history, signal)
      setItems(list)
      setError(null)
    } catch (e) {
      if (e.name !== 'AbortError') setError(errorText(e))
    }
  }, [])

  useEffect(() => {
    const ctrl = new AbortController()
    load(showHistory, ctrl.signal)
    const t = setInterval(() => load(showHistory, ctrl.signal), REFRESH_MS)
    return () => {
      ctrl.abort()
      clearInterval(t)
    }
  }, [load, showHistory])

  const block = async (e) => {
    e.preventDefault()
    const sessionId = form.sessionId.trim()
    if (!sessionId) return
    const minutes = form.minutes ? Number(form.minutes) : null
    if (!window.confirm(`세션 ${sessionId} 을(를) ${minutes ? `${minutes}분 동안` : '해제할 때까지'} 차단할까요? 이 세션의 AI 요청은 모두 거부됩니다.`)) return
    setBusy(sessionId)
    setError(null)
    setNotice(null)
    try {
      await sessionsApi.block(sessionId, { note: form.note.trim(), minutes })
      setNotice(`${sessionId} 차단했습니다.`)
      setForm({ sessionId: '', note: '', minutes: '' })
      await load(showHistory)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(null)
    }
  }

  const release = async (row) => {
    if (!window.confirm(`세션 ${row.session_id} 차단을 풀까요? (${BLOCK_REASON_LABEL[row.reason] ?? row.reason})`)) return
    setBusy(row.session_id)
    setError(null)
    setNotice(null)
    try {
      await sessionsApi.release(row.session_id)
      setNotice(`${row.session_id} 차단을 풀었습니다.`)
      await load(showHistory)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <section>
      <h1>세션 차단</h1>
      <p className="muted">
        카나리 적중·탈취 임계치로 자동 차단된 세션과 운영자가 직접 차단한 세션입니다. 차단 중인 세션의 AI 요청은 거부(429)됩니다.
        카나리 차단은 만료가 없으니 원인을 확인한 뒤 여기서 풀어 주세요. 알림은 Slack·이메일로도 갑니다(docs/ops/alerts.md).
      </p>

      <form className="row adm-block-form adm-search" onSubmit={block}>
        <label>
          세션 ID
          <input
            type="text"
            value={form.sessionId}
            maxLength={128}
            placeholder="AI 사용 기록 화면의 session_id"
            onChange={(e) => setForm({ ...form, sessionId: e.target.value })}
            required
          />
        </label>
        <label>
          메모(선택)
          <input type="text" value={form.note} maxLength={300} onChange={(e) => setForm({ ...form, note: e.target.value })} />
        </label>
        <label>
          기간(분, 비우면 해제까지)
          <input type="number" min={1} max={43200} value={form.minutes} onChange={(e) => setForm({ ...form, minutes: e.target.value })} />
        </label>
        <button type="submit" disabled={busy !== null || !form.sessionId.trim()}>
          수동 차단
        </button>
      </form>

      {error && <p className="error">{error}</p>}
      {notice && <p className="success">{notice}</p>}

      <div className="row adm-search">
        <label className="muted">
          <input type="checkbox" checked={showHistory} onChange={(e) => setShowHistory(e.target.checked)} /> 해제·만료된 이력도 보기
        </label>
      </div>

      {!items && !error && <p className="muted">불러오는 중...</p>}
      {items && (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <caption className="muted">{showHistory ? `최근 ${items.length}건 (이력 포함)` : `차단 중 ${items.length}건`}</caption>
            <thead>
              <tr>
                <th scope="col">세션</th>
                <th scope="col">사용자</th>
                <th scope="col">사유</th>
                <th scope="col">규칙 · 메모</th>
                <th scope="col">차단</th>
                <th scope="col">만료</th>
                <th scope="col">해제</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.session_id} className={r.active ? '' : 'adm-released'}>
                  <td className="adm-mono">{r.session_id}</td>
                  <td className="adm-mono">{r.user_id}</td>
                  <td>
                    <span className={`adm-role adm-reason-${r.reason}`}>{BLOCK_REASON_LABEL[r.reason] ?? r.reason}</span>
                  </td>
                  <td className="muted">
                    {r.rule_id && <span className="adm-mono">{r.rule_id}</span>}
                    {r.rule_id && r.note && ' · '}
                    {r.note}
                  </td>
                  <td className="muted">
                    {fmt(r.created_at)}
                    <br />
                    <span className="adm-mono">{r.blocked_by === 'system' ? '자동' : r.blocked_by}</span>
                  </td>
                  <td className="muted">{r.expires_at ? fmt(r.expires_at) : '해제까지'}</td>
                  <td>
                    {r.active ? (
                      <button onClick={() => release(r)} disabled={busy !== null}>
                        {busy === r.session_id ? '푸는 중...' : '해제'}
                      </button>
                    ) : (
                      <span className="muted">
                        {r.released_at ? `${fmt(r.released_at)} · ${r.released_by === 'system' ? '자동' : r.released_by}` : '만료'}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={7} className="muted">
                    {showHistory ? '차단 이력이 없습니다.' : '차단 중인 세션이 없습니다.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
