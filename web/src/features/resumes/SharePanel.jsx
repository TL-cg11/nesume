import { useCallback, useEffect, useState } from 'react'
import { sharesApi } from './api.js'
import { shortDate } from './ShareTags.jsx'

// 작성자용 멘토 공유 관리(B10 후속, part2_guide 4.44)
// 기간은 날짜로 고른다. 오늘 포함 7일째가 기본, 30일째까지(서버가 다시 검증한다).
const DEFAULT_DAYS = 7
const MAX_DAYS = 30
const STATUS_TEXT = { active: '공유 중', expired: '만료', revoked: '취소' }

const localDate = (offsetDays = 0) => {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  return d.toLocaleDateString('sv-SE') // YYYY-MM-DD(브라우저 시간대)
}

const emptyForm = () => ({ mentor_id: '', mentor_label: '', end_date: localDate(DEFAULT_DAYS - 1) })

export default function SharePanel({ resumeId, onChanged }) {
  const [shares, setShares] = useState([])
  const [showEnded, setShowEnded] = useState(false)
  const [form, setForm] = useState(emptyForm)
  const [confirm, setConfirm] = useState(null) // 다시 공유 확인 문구(409)
  const [editing, setEditing] = useState({}) // share_id → { label?, end_date? }
  const [error, setError] = useState(null)

  const load = useCallback(() => sharesApi.list(resumeId).then(setShares), [resumeId])

  useEffect(() => {
    load().catch((e) => setError(e.message))
  }, [load])

  // 성공하면 true. 목록과 버전 태그·자소서 요약을 다시 불러온다
  const run = async (fn) => {
    try {
      await fn()
      setError(null)
      await load()
      onChanged()
      return true
    } catch (e) {
      setError(e.message)
      return false
    }
  }

  const create = (confirmed = false) =>
    run(async () => {
      try {
        await sharesApi.create(resumeId, { ...form, mentor_id: form.mentor_id.trim(), confirm: confirmed })
        setForm(emptyForm())
        setConfirm(null)
      } catch (e) {
        if (e.status === 409 && !confirmed) {
          setConfirm(e.message)
          return
        }
        throw e
      }
    })

  const edit = (sid, patch) => setEditing((cur) => ({ ...cur, [sid]: { ...cur[sid], ...patch } }))
  const stopEdit = (sid, key) =>
    setEditing((cur) => {
      const { [key]: _, ...rest } = cur[sid] ?? {}
      return { ...cur, [sid]: rest }
    })

  const revoke = (s) => {
    if (!window.confirm(`${s.mentor_label}님과의 공유를 취소할까요? 바로 열람할 수 없게 됩니다.`)) return
    run(() => sharesApi.revoke(s.id))
  }

  const visible = shares.filter((s) => showEnded || s.status === 'active')
  const canCreate = form.mentor_id.trim() && form.mentor_label.trim() && form.end_date

  return (
    <div className="card share-panel">
      <div className="row">
        <h2 className="grow">멘토 공유</h2>
        <label className="muted share-toggle">
          <input type="checkbox" checked={showEnded} onChange={(e) => setShowEnded(e.target.checked)} />
          지난 공유 보기
        </label>
      </div>
      <p className="muted">
        지금 저장된 문항별 최신 버전이 공유됩니다. 이후 수정한 내용은 멘토에게 보이지 않습니다.
      </p>

      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault()
          create(false)
        }}
      >
        <input
          className="grow"
          placeholder="멘토 ID"
          value={form.mentor_id}
          maxLength={128}
          onChange={(e) => setForm({ ...form, mentor_id: e.target.value })}
          aria-label="멘토 ID"
        />
        <input
          placeholder="멘토 이름(나만 보임)"
          value={form.mentor_label}
          maxLength={20}
          onChange={(e) => setForm({ ...form, mentor_label: e.target.value })}
          aria-label="멘토 이름"
        />
        <input
          type="date"
          value={form.end_date}
          min={localDate(0)}
          max={localDate(MAX_DAYS - 1)}
          onChange={(e) => setForm({ ...form, end_date: e.target.value })}
          aria-label="공유 종료일"
        />
        <button type="submit" disabled={!canCreate}>
          공유
        </button>
      </form>
      <p className="muted">종료일 하루가 끝나면 자동으로 만료됩니다. 오늘 포함 최대 {MAX_DAYS}일.</p>

      {confirm && (
        <div className="notice share-confirm">
          <p>{confirm}</p>
          <div className="row">
            <button onClick={() => create(true)}>공유</button>
            <button className="secondary" onClick={() => setConfirm(null)}>
              그만두기
            </button>
          </div>
        </div>
      )}
      {error && <p className="error">{error}</p>}

      <ul className="list share-list">
        {visible.map((s) => {
          const ed = editing[s.id] ?? {}
          const active = s.status === 'active'
          return (
            <li key={s.id} className={active ? '' : 'ended'}>
              <div className="row">
                {ed.label !== undefined ? (
                  <>
                    <input
                      value={ed.label}
                      maxLength={20}
                      onChange={(e) => edit(s.id, { label: e.target.value })}
                      aria-label="멘토 이름 수정"
                    />
                    <button
                      disabled={!ed.label.trim()}
                      onClick={() => run(() => sharesApi.rename(s.id, ed.label.trim())).then((ok) => ok && stopEdit(s.id, 'label'))}
                    >
                      저장
                    </button>
                    <button className="secondary" onClick={() => stopEdit(s.id, 'label')}>
                      취소
                    </button>
                  </>
                ) : (
                  <>
                    <strong>{s.mentor_label}</strong>
                    <button className="link muted" onClick={() => edit(s.id, { label: s.mentor_label })}>
                      이름 수정
                    </button>
                  </>
                )}
                <span className="grow" />
                <span className={active ? 'share-tag' : 'share-tag ended'}>
                  {STATUS_TEXT[s.status]} · {shortDate(s.end_date)}까지
                </span>
              </div>
              <div className="row muted">
                <span className="grow" title={s.mentor_id}>
                  ID {s.mentor_id.slice(0, 8)}… · {shortDate(s.created_at.slice(0, 10))} 공유
                </span>
                {active && ed.end_date === undefined && (
                  <>
                    <button className="secondary" onClick={() => edit(s.id, { end_date: localDate(MAX_DAYS - 1) })}>
                      연장
                    </button>
                    <button className="danger" onClick={() => revoke(s)}>
                      공유 취소
                    </button>
                  </>
                )}
                {active && ed.end_date !== undefined && (
                  <>
                    <input
                      type="date"
                      value={ed.end_date}
                      min={localDate(0)}
                      max={localDate(MAX_DAYS - 1)}
                      onChange={(e) => edit(s.id, { end_date: e.target.value })}
                      aria-label="연장 종료일"
                    />
                    <button onClick={() => run(() => sharesApi.extend(s.id, ed.end_date)).then((ok) => ok && stopEdit(s.id, 'end_date'))}>
                      연장 저장
                    </button>
                    <button className="secondary" onClick={() => stopEdit(s.id, 'end_date')}>
                      취소
                    </button>
                  </>
                )}
              </div>
            </li>
          )
        })}
        {visible.length === 0 && <li className="muted">{showEnded ? '공유 기록이 없습니다.' : '공유 중인 멘토가 없습니다.'}</li>}
      </ul>
    </div>
  )
}
