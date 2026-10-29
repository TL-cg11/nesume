import { useCallback, useEffect, useState } from 'react'
import { resumesApi, sharesApi } from './api.js'
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

const emptyForm = () => ({ mentor_email: '', mentor_label: '', end_date: localDate(DEFAULT_DAYS - 1) })

// 공유할 문항·버전 고르기(10/29): 문항마다 체크(기본: 내용 있는 문항 전부) + 버전 선택(기본: 최신)
function useVersionPicks(resumeId, questions) {
  const [versions, setVersions] = useState({}) // question_id → 버전 목록(최신이 앞)
  const [picks, setPicks] = useState({}) // question_id → version_id | '' (공유 안 함)
  const key = questions.map((q) => `${q.id}:${q.latest_version?.id ?? ''}`).join(',')
  useEffect(() => {
    let alive = true
    Promise.all(questions.map((q) => resumesApi.listVersions(resumeId, q.id).then((v) => [q.id, v])))
      .then((pairs) => {
        if (!alive) return
        setVersions(Object.fromEntries(pairs))
        setPicks(Object.fromEntries(pairs.map(([qid, v]) => [qid, v[0]?.id ?? ''])))
      })
      .catch(() => {})
    return () => { alive = false }
    // 문항·최신 버전이 바뀔 때만 다시 불러온다
  }, [resumeId, key])
  return { versions, picks, setPicks }
}

export default function SharePanel({ resumeId, questions = [], onChanged }) {
  const { versions, picks, setPicks } = useVersionPicks(resumeId, questions)
  const chosen = questions.map((q) => picks[q.id]).filter(Boolean)

  const [shares, setShares] = useState([])
  const [showEnded, setShowEnded] = useState(false)
  const [form, setForm] = useState(emptyForm)
  const [confirm, setConfirm] = useState(null) // 다시 공유 확인 문구(409)
  const [editing, setEditing] = useState({}) // share_id → { label?, end_date? }
  const [error, setError] = useState(null)
  const [comments, setComments] = useState({}) // share_id → 코멘트 목록(펼친 공유만)

  // 목록을 한 번이라도 받았으면 API가 연결된 것 → 이후 404(끝난 공유 등)는 서버 문구 그대로
  const [connected, setConnected] = useState(false)
  const errorText = (e) =>
    e.status === 404 && !connected ? '공유 기능이 아직 서버에 연결되지 않았습니다.' : e.message

  const load = useCallback(
    () => sharesApi.list(resumeId).then((list) => {
      setShares(list)
      setConnected(true)
    }),
    [resumeId],
  )

  // 공유 API가 서버에 아직 없으면(main.py 라우터 등록 전, D) 404. 패널은 그대로 두고 목록 404만 조용히 넘긴다
  // (10/28 사용자 결정). 자소서는 이미 불러온 뒤라 여기서의 404는 연결 누락뿐 — 등록되면 그대로 정상 동작
  useEffect(() => {
    load().catch((e) => e.status !== 404 && setError(errorText(e)))
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
      setError(errorText(e))
      return false
    }
  }

  const create = (confirmed = false) =>
    run(async () => {
      try {
        await sharesApi.create(resumeId, {
          ...form, mentor_email: form.mentor_email.trim(), version_ids: chosen, confirm: confirmed,
        })
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

  const toggleComments = async (sid) => {
    if (comments[sid]) {
      setComments(({ [sid]: _, ...rest }) => rest)
      return
    }
    try {
      const list = await sharesApi.comments(sid)
      setComments((cur) => ({ ...cur, [sid]: list }))
    } catch (e) {
      setError(errorText(e))
    }
  }

  const markRead = async (sid, cid) => {
    try {
      const c = await sharesApi.markRead(sid, cid)
      setComments((cur) => ({ ...cur, [sid]: cur[sid].map((x) => (x.id === cid ? c : x)) }))
      await load()
    } catch (e) {
      setError(errorText(e))
    }
  }

  const visible = shares.filter((s) => showEnded || s.status === 'active')
  const canCreate = form.mentor_email.trim() && form.mentor_label.trim() && form.end_date && chosen.length > 0

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
        공유할 문항과 버전을 고르세요. 공유한 뒤 수정한 내용은 멘토에게 보이지 않습니다.
      </p>

      <div className="share-picks">
        {questions.map((q) => {
          const list = versions[q.id] ?? []
          const on = Boolean(picks[q.id])
          return (
            <div key={q.id} className="share-pick">
              <label className="share-toggle">
                <input type="checkbox" checked={on} disabled={!list.length}
                  onChange={(e) => setPicks({ ...picks, [q.id]: e.target.checked ? list[0]?.id ?? '' : '' })} />
                {q.title}
              </label>
              {list.length ? (
                <select value={picks[q.id] || list[0].id} disabled={!on} aria-label={`${q.title} 공유할 버전`}
                  onChange={(e) => setPicks({ ...picks, [q.id]: e.target.value })}>
                  {list.map((v, i) => (
                    <option key={v.id} value={v.id}>
                      v{v.version_no}{i === 0 ? ' (최신)' : ''} · {v.char_count.toLocaleString()}자
                    </option>
                  ))}
                </select>
              ) : (
                <span className="muted">저장된 내용 없음</span>
              )}
            </div>
          )
        })}
        {questions.length === 0 && <p className="muted">공유할 문항이 없습니다. 먼저 문항을 작성해 주세요.</p>}
      </div>

      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault()
          create(false)
        }}
      >
        <input
          className="grow"
          type="email"
          placeholder="멘토 이메일(멘토로 가입한 계정)"
          value={form.mentor_email}
          maxLength={254}
          onChange={(e) => setForm({ ...form, mentor_email: e.target.value })}
          aria-label="멘토 이메일"
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
                {s.comment_count > 0 && (
                  <button className="secondary" onClick={() => toggleComments(s.id)} aria-expanded={!!comments[s.id]}>
                    코멘트 {s.comment_count}
                    {s.unread_count > 0 && <span className="share-unread"> · 새 {s.unread_count}</span>}
                  </button>
                )}
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
              {comments[s.id] && (
                <ul className="share-comment-list">
                  {comments[s.id].map((c) => (
                    <li key={c.id} className={c.read_at ? '' : 'unread'}>
                      <p className="muted">
                        {c.question_title ?? '삭제된 문항'} · {c.paragraph_index + 1}번째 문단
                      </p>
                      {c.paragraph && <blockquote className="share-comment-quote">{c.paragraph}</blockquote>}
                      <p className="share-comment-body">{c.body}</p>
                      <div className="row">
                        <span className="muted grow">{new Date(c.updated_at).toLocaleString()}</span>
                        {c.read_at ? (
                          <span className="muted">확인함</span>
                        ) : (
                          <button className="secondary" onClick={() => markRead(s.id, c.id)}>
                            확인
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          )
        })}
        {visible.length === 0 && <li className="muted">{showEnded ? '공유 기록이 없습니다.' : '공유 중인 멘토가 없습니다.'}</li>}
      </ul>
    </div>
  )
}
