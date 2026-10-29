// 검사·교정 — 맞춤법과 STAR 를 **따로** 검사한다. 하나만 보고 싶은 사람이 둘 다 기다리지 않게.
//
//   맞춤법   규칙(맞춤법·띄어쓰기) + AI 문장 제안. 고칠 곳을 골라 반영한다
//   STAR    상황·과제·행동·결과가 드러나는지 AI가 판정한다(충분·부족·없음).
//           빠진 요소가 있으면 팝업으로 요소마다 "AI가 작성" / "빼기" 를 묻는다(2026-10-29).
//           ★ AI가 지어 쓴 내용은 실제 경험이 아닐 수 있다. 그래서 묻지 않고 쓰지 않고,
//             결과에서 바뀐 곳과 새로 생긴 숫자를 서버가 짚어 보여준다.

import { useMemo, useState } from 'react'
import StarFillDialog from './StarFillDialog.jsx'
import { applyEdits, diffWords, overlaps, pickNonOverlapping, StaleEdit, toEdits } from './edits.js'
import { reviewApi } from './api.js'

const STATUS = {
  ok: { label: '충분', tone: 'llm' },
  weak: { label: '부족', tone: 'check' },
  missing: { label: '없음', tone: 'danger' },
}

export default function ReviewPanel({
  text, run, busy, onApplied, spelling, setSpelling, star, setStar,
  starFill, setStarFill, starOmit, setStarOmit,
}) {
  const empty = !text.trim()
  const [dialogOpen, setDialogOpen] = useState(false)

  // 보완을 권할 요소 — 충분하지 않고, 사용자가 빼기로 하지 않은 것
  const needs = (result) =>
    result ? result.elements.filter((e) => e.status !== 'ok' && !starOmit.has(e.element)) : []
  const pending = needs(star)

  const checkSpelling = async () => {
    const body = await run('spelling', (signal) => reviewApi.spelling(text, signal))
    if (body) setSpelling(body)
  }

  const checkStar = async () => {
    setStarFill(null)
    const body = await run('star', (signal) => reviewApi.star(text, signal))
    if (!body) return
    setStar(body)
    // ★ 빠진 요소가 있을 때만 바로 묻는다. 약한 요소만 있으면 버튼으로 연다 — 매번 뜨면 성가시다
    if (needs(body).some((e) => e.status === 'missing')) setDialogOpen(true)
  }

  const submitFill = async ({ fill, omit }) => {
    setDialogOpen(false)
    if (omit.length) setStarOmit((cur) => new Set([...cur, ...omit]))
    if (!fill.length) return
    const body = await run('starfill', (signal) => reviewApi.starComplete({ text, fill, omit }, signal))
    if (body) setStarFill(body)
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
            상황·과제·행동·결과가 글에 드러나는지 AI가 판정합니다. 빠진 요소가 있으면 AI가 써
            넣을지, 빼고 갈지 물어봅니다.
          </p>
        )}
        {star && !busy.star && (
          <StarResult
            result={star}
            omitted={starOmit}
            onRestore={(el) => setStarOmit((cur) => new Set([...cur].filter((x) => x !== el)))}
          />
        )}
        {star && !busy.star && pending.length > 0 && (
          <div className="row">
            <span className="grow" />
            <button onClick={() => setDialogOpen(true)} disabled={busy.starfill}>
              {busy.starfill ? 'AI가 쓰는 중...' : `AI로 보완하기 (${pending.length})`}
            </button>
          </div>
        )}
        {busy.starfill && <p className="muted">AI가 고른 요소를 써 넣는 중입니다.</p>}
        {starFill && !busy.starfill && (
          <FillResult
            result={starFill}
            onUse={() =>
              onApplied(
                starFill.body,
                'AI가 보완한 글로 바꿨습니다. 표시됐던 부분이 사실과 맞는지 꼭 확인해 주십시오.',
              )
            }
            onDiscard={() => setStarFill(null)}
          />
        )}
      </section>

      <StarFillDialog
        open={dialogOpen}
        elements={pending}
        onSubmit={submitFill}
        onClose={() => setDialogOpen(false)}
      />
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
                  {/* 바뀐 낱말만 표시하고 나머지는 보통 글씨로 둔다 */}
                  <span className="wr-diff">
                    {e.before !== undefined && <span className="muted">…{e.before}</span>}
                    {diffWords(e.original, e.replacement).map((s, i) =>
                      s.op === 'equal' ? (
                        <span key={i}>{s.text}</span>
                      ) : (
                        <span key={i} className={s.op === 'del' ? 'wr-from' : 'wr-to'}>
                          {s.text}
                        </span>
                      ),
                    )}
                    {e.after !== undefined && <span className="muted">{e.after}…</span>}
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

function StarResult({ result, omitted, onRestore }) {
  const okCount = result.elements.filter((e) => e.status === 'ok').length
  const todo = result.elements.filter((e) => e.status !== 'ok' && !omitted.has(e.element)).length

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
        <span className="muted">
          {okCount === 4
            ? '네 요소가 모두 드러납니다.'
            : todo
              ? `${todo}개를 보완하면 좋습니다.`
              : '빼기로 한 요소 말고는 모두 드러납니다.'}
        </span>
      </div>

      <ul className="list">
        {result.elements.map((e) => {
          const off = omitted.has(e.element) && e.status !== 'ok'
          return (
            <li key={e.element} className="wr-star-row">
              <div className="row">
                <strong className="grow">{e.name}</strong>
                {off ? (
                  <>
                    <span className="wr-badge">빼기로 함</span>
                    <button className="secondary wr-small" onClick={() => onRestore(e.element)}>
                      되돌리기
                    </button>
                  </>
                ) : (
                  <span className={`wr-badge ${STATUS[e.status].tone}`}>{STATUS[e.status].label}</span>
                )}
              </div>
              {e.quote && <p className="wr-quote">{`"${e.quote}"`}</p>}
              {!off && e.comment && <p className="reason">{e.comment}</p>}
              {!off && e.question && <p className="wr-question">{e.question}</p>}
            </li>
          )
        })}
      </ul>
    </>
  )
}

// AI가 보완한 글. ★ 바뀐 곳은 서버가 원문과 비교해 준 것이다 — 모델의 자기 신고가 아니다
function FillResult({ result, onUse, onDiscard }) {
  if (result.llm_unavailable) {
    return <p className="notice">AI를 쓸 수 없어 보완하지 못했습니다. 잠시 후 다시 시도해 주십시오.</p>
  }
  if (result.blocked_reason) return <p className="error">해당 요청은 처리할 수 없습니다.</p>
  if (!result.body) {
    return result.notices.map((n) => (
      <p key={n} className="notice">{n}</p>
    ))
  }

  return (
    <div className="card wr-rewrite stack">
      <div className="row">
        <strong className="grow">AI가 보완한 글</strong>
        <span className="muted">{result.char_count.toLocaleString()}자</span>
        <span className="wr-badge check">확인 필요</span>
      </div>
      <p>
        {result.segments.map((s, i) =>
          s.op === 'equal' ? (
            <span key={i}>{s.before}</span>
          ) : (
            <span key={i}>
              {s.before && <span className="wr-from">{s.before}</span>}
              {s.after && <mark className="wr-ai">{s.after}</mark>}
            </span>
          ),
        )}
      </p>
      <p className="muted">색칠된 부분이 AI가 새로 쓰거나 고친 곳입니다. 실제와 다르면 고친 뒤 쓰십시오.</p>
      {result.new_numbers.length > 0 && (
        <p className="notice">
          원문에 없던 숫자: {result.new_numbers.join(', ')} — AI가 만든 값일 수 있습니다. 실제 수치로
          바꿔 주십시오.
        </p>
      )}
      <div className="row">
        <button onClick={onUse}>이 글로 바꾸기</button>
        <button className="secondary" onClick={onDiscard}>
          버리기
        </button>
      </div>
    </div>
  )
}
