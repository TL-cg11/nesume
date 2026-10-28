import { useCallback, useEffect, useState } from 'react'
import { applicationsApi } from './api.js'
import './applications.css'

// 상태 5단계(백엔드 APPLICATION_STATUSES와 동일 순서). [값, 표시 라벨]
const STATUS = [
  ['applied', '지원'],
  ['document_passed', '서류 합격'],
  ['interview', '면접'],
  ['final', '최종 합격'],
  ['rejected', '불합격'],
]
const EMPTY_FORM = { status: 'applied', applied_at: '', memo: '' }

export default function ApplicationsPage() {
  const [items, setItems] = useState(null) // null = 불러오는 중
  const [stats, setStats] = useState(null)
  const [dueIds, setDueIds] = useState(() => new Set())
  const [creating, setCreating] = useState(false)
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

  const changeStatus = async (app, status) => {
    if (status === app.status) return
    setSavingId(app.id)
    try {
      await applicationsApi.updateStatus(app.id, status)
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setSavingId(null)
    }
  }

  const move = (app, dir) => {
    const i = STATUS.findIndex(([v]) => v === app.status)
    const ni = Math.max(0, Math.min(STATUS.length - 1, i + dir))
    if (ni !== i) changeStatus(app, STATUS[ni][0])
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

  const card = (app) => (
    <article key={app.id} className="app-card">
      <div className="app-card-top">
        <div>
          <div className="app-card-title">{app.posting?.company_name || '공고 미연결'}</div>
          {app.posting?.title && <div className="app-card-sub">{app.posting.title}</div>}
        </div>
        {dueIds.has(app.id) && <span className="app-due">마감 임박</span>}
      </div>
      <div className="app-card-meta">
        {app.applied_at && <span>지원일 {app.applied_at}</span>}
        {app.days_until != null && <span>마감 D-{app.days_until}</span>}
        {app.posting?.region_name && <span>{app.posting.region_name}</span>}
        {app.posting && app.posting.is_active === false && <span>마감된 공고</span>}
      </div>
      {app.memo && <p className="app-card-memo">{app.memo}</p>}
      <div className="app-card-actions">
        <button
          className="app-mini-btn"
          disabled={savingId === app.id || app.status === STATUS[0][0]}
          onClick={() => move(app, -1)}
          aria-label="이전 단계"
        >
          ← 이전
        </button>
        <button
          className="app-mini-btn"
          disabled={savingId === app.id || app.status === STATUS[STATUS.length - 1][0]}
          onClick={() => move(app, 1)}
          aria-label="다음 단계"
        >
          다음 →
        </button>
        <span className="app-spacer" />
        <button className="app-mini-btn danger" onClick={() => remove(app)}>
          삭제
        </button>
      </div>
    </article>
  )

  return (
    <div className="app-page">
      <div className="app-page-head">
        <div>
          <p className="eyebrow">CAREER TRACK</p>
          <h1 className="page-heading">지원 현황</h1>
          <p className="page-subtitle">지원한 공고의 진행 단계를 한눈에 관리합니다.</p>
        </div>
        {!creating && (
          <button className="btn-primary" onClick={() => setCreating(true)}>
            지원 추가
          </button>
        )}
      </div>

      {error && <p className="app-error">{error}</p>}

      {creating && (
        <form className="panel app-create" onSubmit={create}>
          <div className="panel-heading">
            <div>
              <h3>지원 추가</h3>
              <p>공고·자소서 연결은 공고 추천 화면에서 지원할 때 자동으로 연결됩니다.</p>
            </div>
          </div>
          <div className="app-create-row">
            <label className="field-label" htmlFor="new-status">상태</label>
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
            <label className="field-label" htmlFor="new-date">지원일</label>
            <input
              id="new-date"
              type="date"
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
            <button type="submit" className="btn-primary">추가</button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => { setCreating(false); setForm(EMPTY_FORM) }}
            >
              취소
            </button>
          </div>
        </form>
      )}

      {stats && (
        <div className="app-stats-grid">
          <div className="stat-card">
            <div className="stat-card-label">전체 지원</div>
            <div className="stat-card-value">{total}건</div>
            <div className="stat-card-detail">등록된 지원 기록</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-label">진행 중</div>
            <div className="stat-card-value">{inProgress}건</div>
            <div className="stat-card-detail">지원·서류·면접 단계</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-label">마감 임박</div>
            <div className="stat-card-value">{dueIds.size}건</div>
            <div className="stat-card-detail">마감이 가까운 지원</div>
          </div>
          <div className="stat-card">
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
              <section key={v} className="panel">
                <div className="panel-heading">
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
