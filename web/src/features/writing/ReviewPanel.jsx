// 검사·교정 — A7(맞춤법·STAR)과 A13(글자 수·문체)을 버튼 한 번으로 본다.
//
// 결과는 세 덩어리다.
//   요약       글자 수 · 문체 · STAR — 지금 글이 어떤 상태인지
//   고칠 곳    글을 바꾸는 제안. 맞춤법·AI 문장 제안·분량 줄이기를 **한 목록**에서 고른다
//   직접 고칠 것  무엇으로 바꿀지 글쓴이만 아는 것 (상투어·빠진 STAR·문체가 다른 문장)
//
// ★ 모델은 글자 수를 세지 못한다. 서버가 다시 세서 맞지 않으면 버리고 이유를 돌려주므로,
//   화면은 그 이유(rejected_reason)를 **그대로 보여준다.** 숨기면 사용자는 고장으로 본다.

import { useMemo, useState } from 'react'
import { applyEdits, overlaps, pickNonOverlapping, StaleEdit, toEdits } from './edits.js'
import { reviewApi } from './api.js'

const STAR = [
  ['S', '상황'],
  ['T', '과제'],
  ['A', '행동'],
  ['R', '결과'],
]

export default function ReviewPanel({ text, tone, limit, result, setResult, run, isBusy, onApplied }) {
  const [accepted, setAccepted] = useState(() => new Set())
  const [stale, setStale] = useState(false)

  // 결과는 글이 바뀌면 부모가 비운다. 그래서 여기 text 는 검사한 그 글이다
  const edits = useMemo(
    () => (result ? toEdits(text, result.proofread, result.style) : []),
    [text, result],
  )

  const check = async () => {
    const body = await run((signal) => reviewApi.check({ text, limit, targetTone: tone }, signal))
    if (!body) return
    setResult(body)
    setAccepted(new Set())
    setStale(false)
  }

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

  const applyAccepted = () => {
    const chosen = edits.filter((e) => accepted.has(e.id))
    try {
      const next = applyEdits(text, chosen)
      setAccepted(new Set())
      onApplied(next, `${chosen.length}건을 반영했습니다 (${next.length.toLocaleString()}자). 바뀐 글을 확인해 주십시오.`)
    } catch (e) {
      if (e instanceof StaleEdit) setStale(true)
      else throw e
    }
  }

  return (
    <div className="stack">
      <div className="row">
        <span className="muted grow">
          맞춤법·띄어쓰기는 규칙으로, 문장 다듬기와 분량 맞추기는 AI가 제안합니다.
        </span>
        <button onClick={check} disabled={isBusy || !text.trim()}>
          {isBusy ? '검사하는 중...' : result ? '다시 검사' : '검사하기'}
        </button>
      </div>

      {isBusy && <p className="muted">AI까지 보느라 몇 초 걸립니다.</p>}
      {!isBusy && !result && (
        <p className="muted">
          왼쪽에 글을 넣고 검사하면 고칠 곳을 한 목록으로 보여 드립니다. 글자 수 제한을 넣으면
          분량도 함께 맞춰 드립니다.
        </p>
      )}

      {!isBusy && result && (
        <Result
          result={result}
          edits={edits}
          accepted={accepted}
          setAccepted={setAccepted}
          stale={stale}
          toggle={toggle}
          onApply={applyAccepted}
          onUseRewrite={() =>
            onApplied(result.style.rewrite.text, 'AI가 다시 쓴 글로 바꿨습니다. 사실이 맞는지 확인해 주십시오.')
          }
        />
      )}
    </div>
  )
}

function Result({ result, edits, accepted, setAccepted, stale, toggle, onApply, onUseRewrite }) {
  const { proofread, style } = result
  const guidance = proofread.suggestions.filter((s) => !s.is_replacement)
  const offTone = style.tone.off_tone
  const llmUnavailable = proofread.llm_unavailable || style.llm_unavailable
  const blocked = proofread.blocked_reason || style.blocked_reason

  return (
    <>
      <Summary proofread={proofread} style={style} />

      {llmUnavailable && <p className="notice">AI를 쓸 수 없어 규칙 검사 결과만 보여 드립니다.</p>}
      {/* 차단 안내는 어느 규칙에 걸렸는지 알려주지 않는다 — 알려 주면 그걸 피해 다시 넣을 수 있다 */}
      {blocked && <p className="notice">AI 응답이 안전 검사에서 걸러져 규칙 검사 결과만 보여 드립니다.</p>}
      {stale && <p className="error">글이 바뀌어 제안 위치가 맞지 않습니다. 다시 검사해 주십시오.</p>}

      {edits.length === 0 && guidance.length === 0 && offTone.length === 0 && !style.rewrite && (
        <p className="success">고칠 곳을 찾지 못했습니다.</p>
      )}

      {edits.length > 0 && (
        <>
          <div className="row">
            <strong className="grow">고칠 곳 {edits.length}건</strong>
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
            <button onClick={onApply} disabled={accepted.size === 0}>
              선택한 {accepted.size}건 반영
            </button>
          </div>
        </>
      )}

      {style.rewrite && (
        <div className="card wr-rewrite">
          <div className="row">
            <strong className="grow">AI가 조건에 맞춰 다시 쓴 글</strong>
            <span className="wr-badge">{style.rewrite.count.total.toLocaleString()}자</span>
            <span className="wr-badge check">확인 필요</span>
          </div>
          <p>{style.rewrite.text}</p>
          {/* 서버가 길이·문체·새 숫자는 검증했다. 사실관계(누가·무엇을)는 글쓴이만 확인할 수 있다 */}
          <p className="muted">글자 수와 숫자는 서버가 다시 확인했습니다. 내용이 사실과 맞는지 읽어 보십시오.</p>
          <div className="row">
            <button onClick={onUseRewrite}>이 글로 바꾸기</button>
          </div>
        </div>
      )}
      {style.rejected_reason && (
        <p className="notice">
          AI가 다시 쓴 글이 조건을 지키지 못해 쓰지 않았습니다 — {style.rejected_reason}. 고칠 곳을
          반영한 뒤 다시 검사하거나 다시 쓰기 탭을 써 보십시오.
        </p>
      )}

      {(guidance.length > 0 || offTone.length > 0) && (
        <>
          <strong>직접 고칠 것 {guidance.length + offTone.length}건</strong>
          <p className="muted">무엇으로 바꿀지는 글쓴이만 알 수 있어 대안을 넣지 않았습니다.</p>
          <ul className="list">
            {offTone.map((s) => (
              <li key={`tone-${s.start}`} className="wr-item guidance">
                <p>{`"${s.text}"`}</p>
                <p className="reason">
                  <span className="wr-badge check">{s.tone_name ?? '문체'}</span> 목표 문체와 다른
                  문장입니다.
                </p>
              </li>
            ))}
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

// 지금 글의 상태 세 가지를 한 줄로
function Summary({ proofread, style }) {
  const { count, over_by: overBy, tone } = style
  const present = new Set(proofread.star.present)

  return (
    <div className="card wr-summary">
      <div>
        <span className="muted">글자 수</span>
        <strong>{count.total.toLocaleString()}자</strong>
        {overBy > 0 ? (
          <span className="wr-badge check">{overBy.toLocaleString()}자 초과</span>
        ) : (
          <span className="muted">공백 제외 {count.without_spaces.toLocaleString()}자</span>
        )}
      </div>
      <div>
        <span className="muted">문체</span>
        <strong>{tone.main_name ?? '판정 불가'}</strong>
        {tone.is_mixed && <span className="wr-badge check">섞여 있음</span>}
      </div>
      <div>
        <span className="muted">STAR 구성</span>
        <span className="wr-star-marks">
          {STAR.map(([k, name]) => (
            <span
              key={k}
              className={present.has(k) ? 'wr-star-mark on' : 'wr-star-mark'}
              title={`${name} ${present.has(k) ? '있음' : '없음'}`}
            >
              {k}
            </span>
          ))}
        </span>
      </div>
    </div>
  )
}
