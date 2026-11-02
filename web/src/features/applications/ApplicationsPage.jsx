import { useCallback, useEffect, useState } from 'react'
import { applicationsApi } from './api.js'
import { safeUrl } from '../safeUrl.js'
import '../c-common.css'
import './applications.css'

// 상태 4단계(백엔드 APPLICATION_STATUSES와 동일 순서, 2026-10-28 불합격 삭제). [값, 표시 라벨]
const STATUS = [
  ['applied', '지원'],
  ['document_passed', '서류 합격'],
  ['interview', '면접'],
  ['final', '최종 합격'],
]
const EMPTY_FORM = { status: 'applied', applied_at: '', memo: '' }

const byPosition = (a, b) => (a.position ?? 0) - (b.position ?? 0)

// '2026-11-02' → '11/02' (마감일 옆 정확한 날짜)
const shortDate = (iso) => iso.slice(5).replace('-', '/')

export default function ApplicationsPage() {
  const [items, setItems] = useState(null) // null = 불러오는 중
  const [stats, setStats] = useState(null)
  const [dueIds, setDueIds] = useState(() => new Set())
  const [creating, setCreating] = useState(false)
  const [dragId, setDragId] = useState(null) // 끌고 있는 카드
  const [overCol, setOverCol] = useState(null) // 끌어다 올린 열(강조 표시)
  const [dropAt, setDropAt] = useState(null) // { status, index } — 놓일 자리(선 표시)
  const [form, setForm] = useState(EMPTY_FORM)
  const [savingId, setSavingId] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async (signal) => {
    try {
      const [list, s, due] = await Promise.all([
        applicationsApi.list(),
        applicationsApi.stats(),
        applicationsApi.dueSoon(),
      ])
      if (signal?.aborted) return
      setItems(list)
      setStats(s)
      setDueIds(new Set(due.map((d) => d.id)))
      setError(null)
    } catch (e) {
      if (e.name === 'AbortError') return
      setError(e.message)
      setItems([])
    }
  }, [])

  useEffect(() => {
    const ctrl = new AbortController()
    load(ctrl.signal)
    return () => ctrl.abort()
  }, [load])

  const create = async (e) => {
    e.preventDefault()
    try {
      const body = { status: form.status }
      if (form.applied_at) body.applied_at = form.applied_at
      const memo = form.memo.trim()
      if (memo) body.memo = memo
      await applicationsApi.create(body)
      setForm(EMPTY_FORM)
      setCreating(false)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  // 드래그로 놓은 자리에 넣는다: 그 열의 새 순서를 한 번에 저장(PUT /applications/order).
  // 다른 열에서 끌어오면 상태도 바뀐다. 화면은 먼저 옮기고(낙관적), 실패하면 다시 불러와 되돌린다.
  const moveTo = async (app, status, index) => {
    const column = (items ?? []).filter((a) => a.status === status && a.id !== app.id)
    const at = Math.max(0, Math.min(index, column.length))
    const ordered = [...column.slice(0, at), { ...app, status }, ...column.slice(at)]
    const pos = new Map(ordered.map((a, i) => [a.id, i]))
    setSavingId(app.id)
    setItems((prev) =>
      prev.map((a) => (pos.has(a.id) ? { ...a, status, position: pos.get(a.id) } : a)).sort(byPosition),
    )
    try {
      await applicationsApi.reorder(status, ordered.map((a) => a.id))
      await load()
    } catch (e) {
      setError(`순서를 저장하지 못했습니다: ${e.message}`)
      await load()
    } finally {
      setSavingId(null)
    }
  }

  const onDrop = (e, status) => {
    e.preventDefault()
    const id = e.dataTransfer.getData('text/plain') || dragId
    const app = (items ?? []).find((a) => a.id === id)
    const groupLen = (items ?? []).filter((a) => a.status === status && a.id !== id).length
    const index = dropAt && dropAt.status === status ? dropAt.index : groupLen
    setOverCol(null)
    setDropAt(null)
    setDragId(null)
    if (!app) return
    // 같은 열에서 자기보다 아래 자리로 옮기면, 자기 자신이 빠진 만큼 한 칸 당겨진다
    const group = (items ?? []).filter((a) => a.status === status)
    const from = group.findIndex((a) => a.id === id)
    const adj = from !== -1 && from < index ? index - 1 : index
    if (from !== -1 && adj === from) return // 제자리
    moveTo(app, status, adj)
  }

  const remove = async (app) => {
    const name = app.posting?.company_name || '이 지원 기록'
    if (!window.confirm(`'${name}'을(를) 삭제할까요?`)) return
    try {
      await applicationsApi.remove(app.id)
      load()
    } catch (e) {
      setError(e.message)
    }
  }

  const total = items?.length ?? 0
  const inProgress = (items ?? []).filter((a) =>
    ['applied', 'document_passed', 'interview'].includes(a.status),
  ).length

  const card = (app, idx) => {
    // 카드 칸을 누르면 원문(새 탭). 드래그로 옮길 땐 브라우저가 click을 내지 않는다
    const href = safeUrl(app.posting?.url)
    const open = () => href && window.open(href, '_blank', 'noopener,noreferrer')
    return (
    <article
      key={app.id}
      className={`app-card${href ? ' app-card-link' : ''}${dragId === app.id ? ' dragging' : ''}${
        savingId === app.id ? ' saving' : ''
      }${
        dropAt && dropAt.status === app.status && dropAt.index === idx ? ' drop-before' : ''
      }${dropAt && dropAt.status === app.status && dropAt.index === idx + 1 && dropAt.last ? ' drop-after' : ''}`}
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && e.target === e.currentTarget) open()
      }}
      {...(href ? { role: 'link', tabIndex: 0, title: '공고 원문 열기' } : {})}
      onDragOver={(e) => {
        // 카드 위쪽 절반이면 그 앞, 아래쪽 절반이면 그 뒤
        const r = e.currentTarget.getBoundingClientRect()
        const after = e.clientY > r.top + r.height / 2
        const index = after ? idx + 1 : idx
        if (!dropAt || dropAt.status !== app.status || dropAt.index !== index) {
          setDropAt({ status: app.status, index, last: after })
        }
      }}
      draggable={savingId !== app.id}
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', app.id)
        e.dataTransfer.effectAllowed = 'move'
        setDragId(app.id)
      }}
      onDragEnd={() => {
        setDragId(null)
        setOverCol(null)
        setDropAt(null)
      }}
    >
      <button
        className="app-card-x"
        onClick={(e) => {
          e.stopPropagation()
          remove(app)
        }}
        onKeyDown={(e) => e.stopPropagation()}
        aria-label="지원 기록 삭제"
        title="삭제"
      >
        ×
      </button>
      <div className="app-card-top">
        <div>
          <div className="app-card-title">{app.posting?.company_name || '공고 미연결'}</div>
          {app.posting?.title && <div className="app-card-sub">{app.posting.title}</div>}
        </div>
      </div>
      <div className="app-card-meta">
        {app.posting?.region_name && <span>{app.posting.region_name}</span>}
        {app.applied_at && <span>지원 날짜 {app.applied_at}</span>}
        {dueIds.has(app.id) && <span className="app-due">마감 임박</span>}
        {app.days_until != null && (
          <span>
            마감 D-{app.days_until}
            {app.posting?.closes_on && ` (${shortDate(app.posting.closes_on)})`}
          </span>
        )}
        {app.posting && app.posting.is_active === false && <span>마감된 공고</span>}
      </div>
      {/* 예전 기록은 메모에 공고 제목이 그대로 들어 있다 → 제목과 같으면 숨김 */}
      {app.memo && app.memo !== app.posting?.title && <p className="app-card-memo">{app.memo}</p>}
    </article>
    )
  }

  return (
    <div className="app-page">
      <div className="app-page-head">
        <div>
          <p className="c-eyebrow">CAREER TRACK</p>
          <h1 className="c-page-heading">지원 현황</h1>
          <p className="c-page-subtitle">지원한 공고의 진행 단계를 한눈에 관리합니다.</p>
        </div>
        {!creating && (
          <button className="c-btn-primary" onClick={() => setCreating(true)}>
            지원 추가
          </button>
        )}
      </div>

      {error && <p className="app-error">{error}</p>}

      {creating && (
        <form className="c-panel app-create" onSubmit={create}>
          <div className="c-panel-heading">
            <div>
              <h3>지원 추가</h3>
              <p>공고·자소서 연결은 공고 추천 화면에서 지원할 때 자동으로 연결됩니다.</p>
            </div>
          </div>
          <div className="app-create-row">
            <label className="c-field-label" htmlFor="new-status">상태</label>
            <select
              id="new-status"
              className="field"
              value={form.status}
              onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}
            >
              {STATUS.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
            <label className="c-field-label" htmlFor="new-date">지원 날짜</label>
            <input
              id="new-date"
              type="date"
              // max가 없으면 브라우저가 연도를 6자리까지 받는다(서버는 4자리만 파싱 → 422)
              max="9999-12-31"
              className="field"
              value={form.applied_at}
              onChange={(e) => setForm((f) => ({ ...f, applied_at: e.target.value }))}
            />
          </div>
          <textarea
            className="field"
            aria-label="메모"
            placeholder="메모 (선택)"
            value={form.memo}
            onChange={(e) => setForm((f) => ({ ...f, memo: e.target.value }))}
          />
          <div className="app-create-row">
            <button type="submit" className="c-btn-primary">추가</button>
            <button
              type="button"
              className="c-btn-secondary"
              onClick={() => { setCreating(false); setForm(EMPTY_FORM) }}
            >
              취소
            </button>
          </div>
        </form>
      )}

      {stats && (
        <div className="app-stats-grid">
          <div className="c-stat-card">
            <div className="stat-card-label">전체 지원</div>
            <div className="stat-card-value">{total}건</div>
            <div className="stat-card-detail">등록된 지원 기록</div>
          </div>
          <div className="c-stat-card">
            <div className="stat-card-label">진행 중</div>
            <div className="stat-card-value">{inProgress}건</div>
            <div className="stat-card-detail">지원·서류·면접 단계</div>
          </div>
          <div className="c-stat-card">
            <div className="stat-card-label">마감 임박</div>
            <div className="stat-card-value">{dueIds.size}건</div>
            <div className="stat-card-detail">마감이 가까운 지원</div>
          </div>
          <div className="c-stat-card">
            <div className="stat-card-label">최종 합격</div>
            <div className="stat-card-value">{stats.final ?? 0}건</div>
            <div className="stat-card-detail">최종 단계</div>
          </div>
        </div>
      )}

      {items === null ? (
        <p className="app-state">불러오는 중...</p>
      ) : items.length === 0 ? (
        <p className="app-state">아직 지원 기록이 없습니다. “지원 추가”로 시작하세요.</p>
      ) : (
        <div className="app-board">
          {STATUS.map(([v, l]) => {
            const group = items.filter((a) => a.status === v)
            return (
              <section
                key={v}
                className={`c-panel app-col${overCol === v ? ' app-col-over' : ''}`}
                onDragOver={(e) => {
                  e.preventDefault()
                  e.dataTransfer.dropEffect = 'move'
                  if (overCol !== v) setOverCol(v)
                  // 카드가 아닌 빈 곳 위면 열 맨 아래
                  if (e.target === e.currentTarget && (!dropAt || dropAt.status !== v || dropAt.index !== group.length)) {
                    setDropAt({ status: v, index: group.length, last: true })
                  }
                }}
                onDragLeave={(e) => {
                  if (!e.currentTarget.contains(e.relatedTarget)) {
                    setOverCol(null)
                    setDropAt(null)
                  }
                }}
                onDrop={(e) => onDrop(e, v)}
              >
                <div className="c-panel-heading">
                  <div>
                    <h3>
                      {l}
                      <span className="app-col-count">{group.length}</span>
                    </h3>
                  </div>
                </div>
                {group.length === 0 ? (
                  <p className="app-empty-col">없음</p>
                ) : (
                  group.map(card)
                )}
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}
