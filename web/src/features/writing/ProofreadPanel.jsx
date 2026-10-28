// A7 — 맞춤법·문장 개선 + STAR 보완 패널.
//
// 본문은 WritingPage 가 들고 있고 여기는 결과만 다룬다. 글이 바뀌면 부모가
// 결과를 비우므로 이 패널은 "지금 글에 대한 결과"만 신경 쓰면 된다.

import { useState } from 'react'
import StarPanel from './StarPanel.jsx'
import SuggestionItem from './SuggestionItem.jsx'
import { writingApi } from './api.js'

export default function ProofreadPanel({ text, result, setResult, run, isBusy, onApplied }) {
  const [accepted, setAccepted] = useState(() => new Set())

  const proofread = async (useLlm) => {
    const body = await run((signal) => writingApi.proofread(text, useLlm, signal))
    if (!body) return
    setResult(body)
    setAccepted(new Set())
  }

  const toggle = (id) =>
    setAccepted((cur) => {
      const next = new Set(cur)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const applyAccepted = async () => {
    const body = await run((signal) =>
      writingApi.apply(text, result.suggestions, [...accepted], signal),
    )
    if (!body) return
    setAccepted(new Set())
    onApplied(
      body.text,
      `${body.applied}건을 반영했습니다. 바뀐 글을 확인한 뒤 자소서에 붙여 넣으십시오.`,
    )
  }

  const replaceable = result?.suggestions.filter((s) => s.is_replacement) ?? []
  const guidance = result?.suggestions.filter((s) => !s.is_replacement) ?? []

  return (
    <div className="stack">
      <div className="row">
        <span className="muted grow">맞춤법·띄어쓰기는 규칙으로, 문장 다듬기는 AI가 제안합니다.</span>
        <button className="secondary" onClick={() => proofread(false)} disabled={isBusy || !text.trim()}>
          규칙만 검사
        </button>
        <button onClick={() => proofread(true)} disabled={isBusy || !text.trim()}>
          AI까지 검사
        </button>
      </div>

      {isBusy && <p className="muted">검사하는 중...</p>}
      {!isBusy && !result && <p className="muted">검사하면 결과가 여기에 나옵니다.</p>}

      {!isBusy && result && (
        <>
          <StarPanel star={result.star} />

          {result.llm_unavailable && (
            <p className="notice">AI 모델이 아직 연결되지 않아 규칙 검사만 했습니다.</p>
          )}
          {result.blocked_reason && (
            <p className="notice">
              AI 응답이 안전 검사에서 걸러졌습니다({result.blocked_reason}). 규칙 검사 결과만
              보여 드립니다.
            </p>
          )}

          {result.suggestions.length === 0 && <p className="muted">고칠 곳을 찾지 못했습니다.</p>}

          {replaceable.length > 0 && (
            <>
              <div className="row">
                <strong className="grow">고칠 곳 {replaceable.length}건</strong>
                <button
                  className="secondary"
                  onClick={() => setAccepted(new Set(replaceable.map((s) => s.id)))}
                >
                  모두 선택
                </button>
                <button className="secondary" onClick={() => setAccepted(new Set())}>
                  선택 해제
                </button>
              </div>
              <ul className="list">
                {replaceable.map((s) => (
                  <SuggestionItem key={s.id} item={s} checked={accepted.has(s.id)} onToggle={toggle} />
                ))}
              </ul>
              <div className="row">
                <button onClick={applyAccepted} disabled={isBusy || accepted.size === 0}>
                  선택한 {accepted.size}건 반영
                </button>
              </div>
            </>
          )}

          {guidance.length > 0 && (
            <>
              <strong>직접 고쳐야 할 것 {guidance.length}건</strong>
              <p className="muted">무엇으로 바꿀지는 글쓴이만 알 수 있어 대안을 넣지 않았습니다.</p>
              <ul className="list">
                {guidance.map((s) => (
                  <SuggestionItem key={s.id} item={s} checked={false} onToggle={toggle} />
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </div>
  )
}
