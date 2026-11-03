import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { dashboardApi, errorText } from './api.js'
import { Donut, HBars, RatioBar, TimeChart, fmtInt, fmtMs, fmtPct } from './charts.jsx'
import './admin.css'
import './dashboard.css'

// 운영 대시보드(D15 차단 현황 + D14 트래픽). 운영자(MFA) 전용.
// 위: AI 가드레일 판정(감사 로그 집계, GET /admin/dashboard/summary) — 기간·평가 트래픽 포함 여부를 고를 수 있다.
// 아래: HTTP 트래픽(GET /admin/dashboard/traffic) — 응답한 파드 1개 기준. 환경 전체는 CloudWatch 대시보드.
const RANGES = [
  { hours: 1, label: '1시간' },
  { hours: 6, label: '6시간' },
  { hours: 24, label: '24시간' },
  { hours: 24 * 7, label: '7일' },
]
const REFRESH_MS = 30_000

const DECISION = {
  allow: { label: '허용', color: 'var(--ops-allow)' },
  mask: { label: '가림', color: 'var(--ops-mask)' },
  block: { label: '차단', color: 'var(--ops-block)' },
}
const QUERY_TYPE = { normal: '정상', out_of_scope: '범위 밖', sensitive: '민감', exfiltration: '유출 시도', '(없음)': '분류 없음' }
const ROLE = { user: '일반 사용자', mentor: '멘토', operator: '운영자', system: '시스템' }
const STAGE = { classifier: '분류기', retriever: '검색 필터', output_guard: '출력 검사', '(없음)': '단계 없음' }

const fmtTime = (iso) => new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const fmtDateTime = (iso) => new Date(iso).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
const fmtUptime = (s) => (s >= 86400 ? `${Math.floor(s / 86400)}일 ${Math.floor((s % 86400) / 3600)}시간` : s >= 3600 ? `${Math.floor(s / 3600)}시간 ${Math.floor((s % 3600) / 60)}분` : `${Math.floor(s / 60)}분`)
const shortId = (id) => `${id.slice(0, 8)}…`

function Delta({ now, before, invert = false }) {
  if (!before) return <span className="ops-delta muted">직전 기간 {fmtInt(before)}건</span>
  const diff = (now - before) / before
  const up = diff > 0
  const bad = invert ? up : !up
  const cls = diff === 0 ? 'muted' : bad ? 'ops-delta-bad' : 'ops-delta-good'
  return (
    <span className={`ops-delta ${cls}`} title={`직전 기간 ${fmtInt(before)}건`}>
      {diff === 0 ? '변화 없음' : `${up ? '▲' : '▼'} ${fmtPct(Math.abs(diff), 0)}`} <span className="muted">vs 직전</span>
    </span>
  )
}

function Kpi({ label, value, sub, tone }) {
  return (
    <div className={`card ops-kpi ${tone ? `ops-kpi-${tone}` : ''}`}>
      <span className="ops-kpi-label">{label}</span>
      <strong className="ops-kpi-value">{value}</strong>
      {sub && <span className="ops-kpi-sub">{sub}</span>}
    </div>
  )
}

function Panel({ title, caption, children, className = '', action }) {
  return (
    <section className={`card ops-panel ${className}`}>
      <header className="ops-panel-head">
        <div>
          <h2>{title}</h2>
          {caption && <p className="muted">{caption}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  )
}

export default function AdminDashboardPage() {
  const [hours, setHours] = useState(24)
  const [includeTest, setIncludeTest] = useState(false)
  const [auto, setAuto] = useState(true)
  const [summary, setSummary] = useState(null)
  const [traffic, setTraffic] = useState(null)
  const [emails, setEmails] = useState({})
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [updatedAt, setUpdatedAt] = useState(null)
  const [pickedUser, setPickedUser] = useState(null)
  const emailsRef = useRef(emails)
  emailsRef.current = emails

  const trafficMinutes = Math.min(hours * 60, 24 * 60)

  const load = useCallback(
    async (signal) => {
      setLoading(true)
      try {
        const [s, t] = await Promise.all([dashboardApi.summary({ hours, includeTest }, signal), dashboardApi.traffic(trafficMinutes, signal)])
        setSummary(s)
        setTraffic(t)
        setError(null)
        setUpdatedAt(new Date())
        const ids = [...new Set([...s.top_users.map((u) => u.user_id), ...s.recent_events.map((e) => e.user_id)])].filter(
          (id) => !(id in emailsRef.current),
        )
        if (ids.length) {
          const found = await dashboardApi.emails(ids.slice(0, 100)).catch(() => ({}))
          setEmails((cur) => ({ ...cur, ...found }))
        }
      } catch (e) {
        if (e.name !== 'AbortError') setError(errorText(e))
      } finally {
        setLoading(false)
      }
    },
    [hours, includeTest, trafficMinutes],
  )

  useEffect(() => {
    const ctrl = new AbortController()
    load(ctrl.signal)
    return () => ctrl.abort()
  }, [load])

  useEffect(() => {
    if (!auto) return undefined
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, REFRESH_MS)
    return () => clearInterval(id)
  }, [auto, load])

  const who = (id) => emails[id] ?? shortId(id)

  const decisionSeries = useMemo(() => Object.entries(DECISION).map(([key, d]) => ({ key, label: d.label, color: d.color })), [])
  const seriesPoints = useMemo(
    () => (summary ? summary.series.map((p) => ({ at: p.at, values: { allow: p.allow, mask: p.mask, block: p.block } })) : []),
    [summary],
  )
  const trafficPoints = useMemo(
    () => (traffic ? traffic.series.map((p) => ({ at: p.at, values: { requests: p.requests, errors_5xx: p.errors_5xx, client_4xx: p.client_4xx } })) : []),
    [traffic],
  )
  const latencyPoints = useMemo(() => (traffic ? traffic.series.map((p) => ({ at: p.at, values: { p95: p.p95_ms ?? 0 } })) : []), [traffic])

  const bars = (rows, labels) =>
    rows.map((r) => ({ key: r.key, label: labels?.[r.key] ?? r.key, value: r.requests, subValue: r.block, sub: `차단 ${fmtInt(r.block)} · 가림 ${fmtInt(r.mask)}` }))

  const events = useMemo(() => (summary ? summary.recent_events.filter((e) => !pickedUser || e.user_id === pickedUser) : []), [summary, pickedUser])

  const t = summary?.totals
  const tt = traffic?.totals

  return (
    <section className="ops">
      <div className="ops-toolbar">
        <div>
          <h1>운영 대시보드</h1>
          <p className="muted">
            AI 가드레일 판정과 서비스 트래픽을 한눈에. 평가 러너(is_test) 트래픽은 기본으로 뺍니다.
            {summary && (
              <>
                {' '}
                · {fmtDateTime(summary.window_from)} ~ {fmtDateTime(summary.window_to)}
              </>
            )}
          </p>
        </div>
        <div className="ops-controls">
          <div className="ops-seg" role="group" aria-label="기간">
            {RANGES.map((r) => (
              <button key={r.hours} type="button" className={hours === r.hours ? 'on' : ''} onClick={() => setHours(r.hours)}>
                {r.label}
              </button>
            ))}
          </div>
          <label className="ops-check">
            <input type="checkbox" checked={includeTest} onChange={(e) => setIncludeTest(e.target.checked)} /> 평가 트래픽 포함
          </label>
          <label className="ops-check">
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> 30초 자동 갱신
          </label>
          <button type="button" className="secondary" onClick={() => load()} disabled={loading}>
            {loading ? '불러오는 중…' : '새로고침'}
          </button>
          {updatedAt && <span className="muted ops-updated">{fmtTime(updatedAt)} 갱신</span>}
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {!summary && !error && <p className="muted">불러오는 중...</p>}

      {summary && t && (
        <>
          <h2 className="ops-section">AI 가드레일 · 차단 현황</h2>
          <div className="ops-kpis">
            <Kpi label="AI 요청" value={fmtInt(t.requests)} sub={<Delta now={t.requests} before={summary.previous.requests} />} />
            <Kpi label="차단" value={fmtInt(t.block)} sub={<Delta now={t.block} before={summary.previous.block} invert />} tone="block" />
            <Kpi label="가림(마스킹)" value={fmtInt(t.mask)} sub={`판정의 ${fmtPct(t.requests ? t.mask / t.requests : 0)}`} tone="mask" />
            <Kpi label="차단율" value={fmtPct(t.block_rate)} sub={`flag 비율 ${fmtPct(t.flag_rate)}`} />
            <Kpi label="카나리 탐지" value={fmtInt(t.canary_hits)} sub={t.canary_hits ? '유출 시도 의심 — 즉시 확인' : '탐지 없음'} tone={t.canary_hits ? 'block' : 'ok'} />
            <Kpi label="평균 처리 시간" value={fmtMs(t.avg_latency_ms)} sub="가드레일 + LLM 포함" />
          </div>

          <div className="ops-grid ops-grid-wide">
            <Panel title="시간대별 판정 추이" caption={`${summary.step_minutes}분 단위 · 허용·가림·차단을 쌓아 표시`}>
              <TimeChart points={seriesPoints} series={decisionSeries} mode="stack" spanHours={hours} height={220} />
            </Panel>
            <Panel title="판정 비율">
              <Donut
                label="AI 요청"
                items={Object.entries(DECISION).map(([key, d]) => ({ key, label: d.label, color: d.color, value: summary.by_decision.find((c) => c.key === key)?.requests ?? 0 }))}
              />
            </Panel>
          </div>

          <div className="ops-grid ops-grid-4">
            <Panel title="질의 유형별" caption="진한 부분이 차단">
              <HBars items={bars(summary.by_query_type, QUERY_TYPE)} color="var(--ops-c1)" />
            </Panel>
            <Panel title="역할별" caption="진한 부분이 차단">
              <HBars items={bars(summary.by_role, ROLE)} color="var(--ops-c2)" />
            </Panel>
            <Panel title="기능별" caption="요청이 많은 순 12개">
              <HBars items={bars(summary.by_feature)} color="var(--ops-c3)" />
            </Panel>
            <Panel title="차단 단계" caption="어느 레일에서 걸렸는가">
              <HBars items={bars(summary.by_stage, STAGE)} color="var(--ops-c4)" />
            </Panel>
          </div>

          <div className="ops-grid ops-grid-wide">
            <Panel
              title="flag 비율 상위 사용자"
              caption="가드레일에 걸린 비율이 높은 사용자 10명. 행을 누르면 오른쪽 이벤트를 그 사용자로 거릅니다."
              action={pickedUser && <button type="button" className="secondary" onClick={() => setPickedUser(null)}>필터 해제</button>}
            >
              {summary.top_users.length === 0 ? (
                <p className="muted ops-empty-text">이 기간에 flag 가 붙은 요청이 없습니다.</p>
              ) : (
                <div className="adm-table-wrap">
                  <table className="adm-table ops-table">
                    <thead>
                      <tr>
                        <th scope="col">사용자</th>
                        <th scope="col">역할</th>
                        <th scope="col" className="num">요청</th>
                        <th scope="col" className="num">flag</th>
                        <th scope="col" className="num">차단</th>
                        <th scope="col">flag 비율</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.top_users.map((u) => (
                        <tr key={u.user_id} className={`pick ${pickedUser === u.user_id ? 'picked' : ''}`} onClick={() => setPickedUser(pickedUser === u.user_id ? null : u.user_id)}>
                          <td>
                            <span className="ops-who" title={u.user_id}>{who(u.user_id)}</span>
                            {u.canary_hits > 0 && <span className="ops-tag block">카나리 {u.canary_hits}</span>}
                          </td>
                          <td className="muted">{ROLE[u.role] ?? u.role}</td>
                          <td className="num">{fmtInt(u.requests)}</td>
                          <td className="num">{fmtInt(u.flagged)}</td>
                          <td className="num">{fmtInt(u.block)}</td>
                          <td>
                            <span className="ops-meter"><span style={{ width: `${u.flag_rate * 100}%` }} /></span> {fmtPct(u.flag_rate, 0)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
            <Panel
              title="최근 차단·가림·카나리"
              caption={pickedUser ? `${who(pickedUser)} 의 이벤트만` : '최신 20건'}
              action={<Link to="/ai-logs" className="ops-link">전체 기록 →</Link>}
            >
              {events.length === 0 ? (
                <p className="muted ops-empty-text">이 기간에 차단·가림·카나리 이벤트가 없습니다.</p>
              ) : (
                <ul className="ops-events">
                  {events.map((e) => (
                    <li key={e.request_id}>
                      <span className={`ops-tag ${e.canary_hit ? 'block' : e.decision}`}>{e.canary_hit ? '카나리' : DECISION[e.decision]?.label ?? e.decision}</span>
                      <span className="ops-event-body">
                        <span className="ops-who" title={e.user_id}>{who(e.user_id)}</span>
                        <span className="muted"> · {e.feature}{e.query_type ? ` · ${QUERY_TYPE[e.query_type] ?? e.query_type}` : ''}{e.decision_stage ? ` · ${STAGE[e.decision_stage] ?? e.decision_stage}` : ''}</span>
                        {(e.flags.length > 0 || e.rule_id) && (
                          <span className="ops-flags">{[...e.flags, e.rule_id].filter(Boolean).map((f) => <code key={f}>{f}</code>)}</span>
                        )}
                      </span>
                      <time className="muted" dateTime={e.timestamp}>{fmtDateTime(e.timestamp)}</time>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        </>
      )}

      {traffic && tt && (
        <>
          <h2 className="ops-section">
            HTTP 트래픽
            <span className="ops-section-sub">
              파드 <code>{traffic.pod.hostname}</code> · {traffic.pod.env} · v{traffic.pod.version} · 가동 {fmtUptime(traffic.pod.uptime_s)} · 최근 {traffic.window_minutes >= 60 ? `${traffic.window_minutes / 60}시간` : `${traffic.window_minutes}분`}
            </span>
          </h2>
          <p className="muted ops-note">
            이 수치는 응답한 파드 1개의 프로세스 집계입니다(재시작하면 비워짐). 환경 전체 추이·알람은 CloudWatch 대시보드 <code>nesume-{traffic.pod.env}</code> 를 보세요. 평가 트래픽 {fmtInt(tt.test_requests)}건과 헬스 프로브 {fmtInt(tt.probe_requests)}건은 제외했습니다.
          </p>
          <div className="ops-kpis">
            <Kpi label="요청" value={fmtInt(tt.requests)} sub={`분당 ${tt.rpm}`} />
            <Kpi label="5xx 오류율" value={fmtPct(tt.error_rate, 2)} sub={`${fmtInt(tt.errors_5xx)}건 · 알람 기준 2%`} tone={tt.error_rate > 0.02 ? 'block' : 'ok'} />
            <Kpi label="4xx" value={fmtInt(tt.client_4xx)} sub="인증·권한·검증 거부" />
            <Kpi label="p95 지연" value={fmtMs(tt.latency_ms.p95)} sub={`p50 ${fmtMs(tt.latency_ms.p50)} · 알람 기준 3s`} tone={tt.latency_ms.p95 > 3000 ? 'block' : 'ok'} />
            <Kpi label="p99 지연" value={fmtMs(tt.latency_ms.p99)} sub={`평균 ${fmtMs(tt.latency_ms.avg)}`} />
          </div>

          <div className="ops-grid ops-grid-wide">
            <Panel title="요청·오류 추이" caption={`${traffic.step_minutes}분 단위`}>
              <TimeChart
                points={trafficPoints}
                series={[
                  { key: 'requests', label: '요청', color: 'var(--ops-c1)', fill: true },
                  { key: 'client_4xx', label: '4xx', color: 'var(--ops-mask)' },
                  { key: 'errors_5xx', label: '5xx', color: 'var(--ops-block)' },
                ]}
                mode="line"
                spanHours={traffic.window_minutes / 60}
                height={200}
              />
            </Panel>
            <Panel title="p95 지연" caption="구간별 95번째 백분위(ms)">
              <TimeChart points={latencyPoints} series={[{ key: 'p95', label: 'p95', color: 'var(--ops-c2)', fill: true }]} mode="line" spanHours={traffic.window_minutes / 60} height={200} unit="" format={fmtMs} />
            </Panel>
          </div>

          <div className="ops-grid ops-grid-3">
            <Panel title="상태 코드">
              <RatioBar
                items={[
                  { key: '2xx', label: '2xx', value: traffic.status['2xx'], color: 'var(--ops-allow)' },
                  { key: '3xx', label: '3xx', value: traffic.status['3xx'], color: 'var(--ops-c3)' },
                  { key: '4xx', label: '4xx', value: traffic.status['4xx'], color: 'var(--ops-mask)' },
                  { key: '5xx', label: '5xx', value: traffic.status['5xx'], color: 'var(--ops-block)' },
                ]}
              />
              <h3 className="ops-h3">역할별 요청</h3>
              <HBars items={Object.entries(traffic.by_role).map(([k, v]) => ({ key: k, label: ROLE[k] ?? (k === 'anonymous' ? '비로그인' : k), value: v }))} color="var(--ops-c2)" />
            </Panel>
            <Panel title="지연 분포" caption="응답 시간 구간별 건수">
              <HBars
                items={traffic.latency_hist.map((h, i) => ({ key: String(i), label: h.le_ms == null ? '> 10s' : `≤ ${fmtMs(h.le_ms)}`, value: h.count }))}
                color="var(--ops-c1)"
              />
            </Panel>
            <Panel title="라우트별" caption="요청 많은 순 15개 · 5xx 가 있으면 붉게" className="ops-routes">
              <div className="adm-table-wrap">
                <table className="adm-table ops-table">
                  <thead>
                    <tr>
                      <th scope="col">라우트</th>
                      <th scope="col" className="num">요청</th>
                      <th scope="col" className="num">5xx</th>
                      <th scope="col" className="num">p95</th>
                    </tr>
                  </thead>
                  <tbody>
                    {traffic.routes.map((r) => (
                      <tr key={`${r.method} ${r.route}`} className={r.errors_5xx ? 'ops-row-bad' : ''}>
                        <td><code>{r.method}</code> {r.route}</td>
                        <td className="num">{fmtInt(r.requests)}</td>
                        <td className="num">{r.errors_5xx || <span className="muted">0</span>}</td>
                        <td className="num">{fmtMs(r.p95_ms)}</td>
                      </tr>
                    ))}
                    {traffic.routes.length === 0 && (
                      <tr><td colSpan={4} className="muted">아직 요청이 없습니다.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>
        </>
      )}
    </section>
  )
}
