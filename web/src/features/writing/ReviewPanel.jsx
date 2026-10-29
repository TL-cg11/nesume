// 검사·교정 — 맞춤법과 STAR 를 **따로** 검사한다. 하나만 보고 싶은 사람이 둘 다 기다리지 않게.
//
//   맞춤법   규칙(맞춤법·띄어쓰기) + AI 문장 제안. 고칠 곳을 골라 반영한다
//   STAR    상황·과제·행동·결과가 드러나는지 AI가 판정한다(충분·부족·없음).
//           ★ 빠진 것은 **질문**으로만 알려준다. 대신 써 주면 없는 경험을 지어낸다
//           (A7 star.py·2026-10-22 팀 회의와 같은 판단).

import { useMemo, useState } from 'react'
import { applyEdits, overlaps, pickNonOverlapping, StaleEdit, toEdits } from './edits.js'
import { reviewApi } from './api.js'

const STATUS = {
  ok: { label: '충분', tone: 'llm' },
  weak: { label: '부족', tone: 'check' },
  missing: { label: '없음', tone: 'danger' },
}

export default function ReviewPanel({ text, run, busy, onApplied, spelling, setSpelling, star, setStar }) {
  const empty = !text.trim()

  const checkSpelling = async () => {
    const body = await run('spelling', (signal) => reviewApi.spelling(text, signal))
    if (body) setSpelling(body)
  }

  const checkStar = async () => {
    const body = await run('star', (signal) => reviewApi.star(text, signal))
    if (body) setStar(body)
  }

  return (
    <div className="stack">
      <section className="card wr-section">
        <div className="row">
          <strong className="grow">맞춤법·문장</strong>
          <button onClick={checkSpelling} disabled={busy.spelling || empty}>
            {busy.spelling ? '검사하는 중...' : spelling ? '다시 검사' : '맞춤법 검사'}
          </button>
        </div>
        {!spelling && !busy.spelling && (
          <p className="muted">맞춤법·띄어쓰기는 규칙으로, 어색한 문장은 AI가 찾아 고칠 곳을 제안합니다.</p>
        )}
        {spelling && !busy.spelling && (
          <SpellingResult text={text} result={spelling} onApplied={onApplied} />
        )}
      </section>

      <section className="card wr-section">
        <div className="row">
          <strong className="grow">STAR 구성</strong>
          <button onClick={checkStar} disabled={busy.star || empty}>
            {busy.star ? '판정하는 중...' : star ? '다시 판정' : 'STAR 검사'}
          </button>
        </div>
        {!star && !busy.star && (
          <p className="muted">
            상황·과제·행동·결과가 글에 드러나는지 AI가 판정합니다. 부족한 것은 질문으로 알려
            드리고, 내용을 대신 써 넣지는 않습니다.
          </p>
        )}
        {star && !busy.star && <StarResult result={star} />}
      </section>
    </div>
  )
}

function SpellingResult({ text, result, onApplied }) {
  const [accepted, setAccepted] = useState(() => new Set())
  const [stale, setStale] = useState(false)

  // 결과는 글이 바뀌면 부모가 비운다. 그래서 여기 text 는 검사한 그 글이다
  const edits = useMemo(() => toEdits(text, result), [text, result])
  // STAR 안내는 STAR 칸이 맡는다. 여기서도 띄우면 같은 말을 두 번 한다
  const guidance = result.suggestions.filter((s) => !s.is_replacement && s.kind !== 'star')

  // 고르면 그와 겹치는 제안은 풀린다 — 같은 자리를 두 번 바꿀 수 없다
  const toggle = (edit) =>
    setAccepted((cur) => {
      const next = new Set(cur)
      if (next.has(edit.id)) {
        next.delete(edit.id)
        return next
      }
      for (const other of edits) if (next.has(other.id) && overlaps(other, edit)) next.delete(other.id)
      next.add(edit.id)
      return next
    })

  const apply = () => {
    const chosen = edits.filter((e) => accepted.has(e.id))
    try {
      onApplied(applyEdits(text, chosen), `${chosen.length}건을 반영했습니다. 바뀐 글을 확인해 주십시오.`)
    } catch (e) {
      if (e instanceof StaleEdit) setStale(true)
      else throw e
    }
  }

  return (
    <>
      {result.llm_unavailable && <p className="notice">AI를 쓸 수 없어 규칙 검사 결과만 보여 드립니다.</p>}
      {/* 차단 안내는 어느 규칙에 걸렸는지 알려주지 않는다 — 알려 주면 그걸 피해 다시 넣을 수 있다 */}
      {result.blocked_reason && (
        <p className="notice">AI 응답이 안전 검사에서 걸러져 규칙 검사 결과만 보여 드립니다.</p>
      )}
      {stale && <p className="error">글이 바뀌어 제안 위치가 맞지 않습니다. 다시 검사해 주십시오.</p>}
      {edits.length === 0 && guidance.length === 0 && <p className="success">고칠 곳을 찾지 못했습니다.</p>}

      {edits.length > 0 && (
        <>
          <div className="row">
            <span className="grow">고칠 곳 {edits.length}건</span>
            <button className="secondary" onClick={() => setAccepted(pickNonOverlapping(edits))}>
              모두 선택
            </button>
            <button className="secondary" onClick={() => setAccepted(new Set())}>
              선택 해제
            </button>
          </div>
          <ul className="list">
            {edits.map((e) => (
              <li key={e.id} className="wr-item">
                <label className="head">
                  <input type="checkbox" checked={accepted.has(e.id)} onChange={() => toggle(e)} />
                  <span>
                    {e.before !== undefined && <span className="muted">…{e.before}</span>}
                    <span className="wr-from">{e.original}</span>
                    {' → '}
                    <span className="wr-to">{e.replacement || '(삭제)'}</span>
                    {e.after !== undefined && <span className="muted"> {e.after}…</span>}
                  </span>
                </label>
                <p className="reason">
                  {e.tags.map((t) => (
                    <span key={t.label} className={t.tone ? `wr-badge ${t.tone}` : 'wr-badge'}>
                      {t.label}
                    </span>
                  ))}{' '}
                  {e.reason}
                </p>
              </li>
            ))}
          </ul>
          <div className="row">
            <button onClick={apply} disabled={accepted.size === 0}>
              선택한 {accepted.size}건 반영
            </button>
          </div>
        </>
      )}

      {guidance.length > 0 && (
        <>
          <span>직접 고칠 것 {guidance.length}건</span>
          <ul className="list">
            {guidance.map((s) => (
              <li key={s.id} className="wr-item guidance">
                {s.original && <p>{`"${s.original}"`}</p>}
                <p className="reason">{s.reason}</p>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  )
}

function StarResult({ result }) {
  const okCount = result.elements.filter((e) => e.status === 'ok').length

  return (
    <>
      {result.llm_unavailable && (
        <p className="notice">AI를 쓸 수 없어 낱말 단서로만 판정했습니다. 정확하지 않을 수 있습니다.</p>
      )}
      {result.blocked_reason && (
        <p className="notice">AI 응답이 안전 검사에서 걸러져 낱말 단서로만 판정했습니다.</p>
      )}

      <div className="wr-star-marks" aria-label={`STAR ${okCount}/4 충분`}>
        {result.elements.map((e) => (
          <span key={e.element} className={`wr-star-mark ${e.status}`} title={`${e.name} ${STATUS[e.status].label}`}>
            {e.element}
          </span>
        ))}
        <span className="muted">{okCount === 4 ? '네 요소가 모두 드러납니다.' : `${4 - okCount}개를 보완하면 좋습니다.`}</span>
      </div>

      <ul className="list">
        {result.elements.map((e) => (
          <li key={e.element} className="wr-star-row">
            <div className="row">
              <strong className="grow">{e.name}</strong>
              <span className={`wr-badge ${STATUS[e.status].tone}`}>{STATUS[e.status].label}</span>
            </div>
            {e.quote && <p className="wr-quote">{`"${e.quote}"`}</p>}
            {e.comment && <p className="reason">{e.comment}</p>}
            {e.question && <p className="wr-question">{e.question}</p>}
          </li>
        ))}
      </ul>
    </>
  )
}
