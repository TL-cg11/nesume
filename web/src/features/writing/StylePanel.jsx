// A13 — 글자 수·문체 조정 패널.
//
// ★ 모델은 글자 수를 세지 못한다. 서버가 다시 세서 맞지 않으면 버리고 이유를 돌려주므로,
//   화면은 그 이유(rejected_reason)를 **그대로 보여준다.** 숨기면 사용자는 고장으로 본다.

import { useState } from 'react'
import { TONE_NAMES, styleApi } from './api.js'

export default function StylePanel({ text, result, setResult, run, isBusy, onApplied }) {
  const [limit, setLimit] = useState('')
  const [targetTone, setTargetTone] = useState('formal')
  const [accepted, setAccepted] = useState(() => new Set())

  const adjust = async (useLlm) => {
    const body = await run((signal) =>
      styleApi.adjust({ text, limit: Number(limit) || null, targetTone, useLlm }, signal),
    )
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
    const body = await run((signal) => styleApi.apply(text, result.trims, [...accepted], signal))
    if (!body) return
    setAccepted(new Set())
    onApplied(body.text, `${body.applied}건을 반영해 ${body.count.total.toLocaleString()}자가 되었습니다.`)
  }

  const useRewrite = () => onApplied(result.rewrite.text, 'AI가 다시 쓴 글로 바꿨습니다. 사실이 맞는지 확인해 주십시오.')

  return (
    <div className="stack">
      <div className="row">
        <label className="wr-field">
          <span className="muted">글자 수 제한</span>
          <input
            type="number"
            min="1"
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            placeholder="예: 1000"
            aria-label="글자 수 제한"
          />
        </label>
        <label className="wr-field">
          <span className="muted">목표 문체</span>
          <select value={targetTone} onChange={(e) => setTargetTone(e.target.value)} aria-label="목표 문체">
            {Object.entries(TONE_NAMES).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <span className="grow" />
        <button className="secondary" onClick={() => adjust(false)} disabled={isBusy || !text.trim()}>
          규칙만 검사
        </button>
        <button onClick={() => adjust(true)} disabled={isBusy || !text.trim()}>
          AI까지 검사
        </button>
      </div>

      {isBusy && <p className="muted">검사하는 중...</p>}
      {!isBusy && !result && (
        <p className="muted">제한을 넣고 검사하면 줄일 곳과 문체가 섞인 문장을 찾아 드립니다.</p>
      )}

      {!isBusy && result && (
        <>
          <div className="card wr-metric">
            <div className="row">
              <strong className="grow">
                {result.count.total.toLocaleString()}자
                <span className="muted"> (공백 제외 {result.count.without_spaces.toLocaleString()}자)</span>
              </strong>
              {result.over_by > 0 ? (
                <span className="wr-badge check">{result.over_by.toLocaleString()}자 초과</span>
              ) : (
                <span className="wr-badge llm">제한 충족</span>
              )}
            </div>
            {result.rule_count && (
              <p className="muted">
                제안을 모두 반영하면 {result.rule_count.total.toLocaleString()}자
                {result.rule_only_fits ? ' — 제한 안에 듭니다.' : ' — 아직 넘습니다.'}
              </p>
            )}
            <p className="muted">
              문체: {result.tone.main_name ?? '판정 불가'}
              {result.tone.is_mixed && ' — 섞여 있습니다'}
            </p>
          </div>

          {result.questions.length > 0 && (
            <div className="wr-item guidance">
              <strong>분량이 모자랍니다</strong>
              <p className="muted">{result.notice}</p>
              <ul className="list">
                {result.questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </div>
          )}

          {result.tone.off_tone.length > 0 && (
            <>
              <strong>문체가 다른 문장 {result.tone.off_tone.length}건</strong>
              <ul className="list">
                {result.tone.off_tone.map((s) => (
                  <li key={`${s.start}-${s.end}`}>
                    <div className="head">
                      <span className="wr-badge check">{s.tone_name}</span>
                    </div>
                    <p>{s.text}</p>
                  </li>
                ))}
              </ul>
            </>
          )}

          {result.trims.length > 0 && (
            <>
              <div className="row">
                <strong className="grow">줄일 곳 {result.trims.length}건</strong>
                <button
                  className="secondary"
                  onClick={() => setAccepted(new Set(result.trims.map((t) => t.id)))}
                >
                  모두 선택
                </button>
                <button className="secondary" onClick={() => setAccepted(new Set())}>
                  선택 해제
                </button>
              </div>
              <ul className="list">
                {result.trims.map((t) => (
                  <li key={t.id} className="wr-item">
                    <div className="head">
                      <input
                        type="checkbox"
                        checked={accepted.has(t.id)}
                        onChange={() => toggle(t.id)}
                        aria-label={`${t.original} 줄이기`}
                      />
                      <span className="wr-from">{t.original}</span>
                      <span aria-hidden="true">→</span>
                      <span className="wr-to">{t.replacement || '(삭제)'}</span>
                      <span className="wr-badge">-{t.saved}자</span>
                      {t.confidence === 'medium' && <span className="wr-badge check">확인 필요</span>}
                    </div>
                    <p className="reason">{t.reason}</p>
                  </li>
                ))}
              </ul>
              <div className="row">
                <button onClick={applyAccepted} disabled={isBusy || accepted.size === 0}>
                  선택한 {accepted.size}건 반영
                </button>
              </div>
            </>
          )}

          {result.rewrite && (
            <div className="card wr-rewrite">
              <div className="row">
                <strong className="grow">AI가 다시 쓴 글</strong>
                <span className="wr-badge">{result.rewrite.count.total.toLocaleString()}자</span>
                <span className="wr-badge check">확인 필요</span>
              </div>
              <p>{result.rewrite.text}</p>
              <p className="muted">{result.notice}</p>
              <div className="row">
                <button onClick={useRewrite} disabled={isBusy}>
                  이 글로 바꾸기
                </button>
              </div>
            </div>
          )}

          {result.rejected_reason && (
            <p className="notice">
              AI가 다시 쓴 글을 쓰지 않았습니다 — {result.rejected_reason}
            </p>
          )}
          {result.llm_unavailable && (
            <p className="notice">AI 모델이 아직 연결되지 않아 규칙 결과만 보여 드립니다.</p>
          )}
        </>
      )}
    </div>
  )
}
