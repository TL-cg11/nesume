// A7 — 맞춤법·문장 개선 + STAR 보완 화면 (tasks.md A7)
//
// 저장하지 않는다. 다듬은 글은 사용자가 복사해 자소서에 붙인다.
// 버전 저장은 B4 경로를 쓸 예정이고 source 값 규약을 B와 협의 중이다 (2026-10-22).
//
// 프론트 가이드(docs/dev/frontend-guide.md)를 따른다 — theme.css 변수만, 인라인 style 없음,
// 공용 클래스 우선, 기능 클래스는 wr- 접두사, 네 가지 상태 처리.

import { useEffect, useRef, useState } from 'react'
import { MAX_TEXT_LEN, writingApi } from './api.js'
import StarPanel from './StarPanel.jsx'
import SuggestionItem from './SuggestionItem.jsx'
import './writing.css'

export default function WritingPage() {
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [accepted, setAccepted] = useState(() => new Set())
  const [isBusy, setIsBusy] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)
  const ctrlRef = useRef(null)

  // 화면을 떠날 때 진행 중인 요청을 취소한다 (가이드 5절)
  useEffect(() => () => ctrlRef.current?.abort(), [])

  const isTooLong = text.length > MAX_TEXT_LEN

  // 글이 바뀌면 이전 제안의 위치는 더 이상 맞지 않는다.
  // 서버도 409로 막지만, 화면에서 먼저 치워 두는 편이 덜 혼란스럽다.
  const changeText = (v) => {
    setText(v)
    if (result) setResult(null)
    setAccepted(new Set())
    setDone(null)
  }

  const call = async (fn) => {
    ctrlRef.current?.abort()
    const ctrl = new AbortController()
    ctrlRef.current = ctrl
    setIsBusy(true)
    setError(null)
    try {
      return await fn(ctrl.signal)
    } catch (e) {
      if (e.name !== 'AbortError') setError(e)
      return null
    } finally {
      if (ctrlRef.current === ctrl) setIsBusy(false)
    }
  }

  const proofread = async (useLlm) => {
    setDone(null)
    const body = await call((signal) => writingApi.proofread(text, useLlm, signal))
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
    const body = await call((signal) =>
      writingApi.apply(text, result.suggestions, [...accepted], signal),
    )
    if (!body) return
    setText(body.text)
    setResult(null)
    setAccepted(new Set())
    setDone(`${body.applied}건을 반영했습니다. 바뀐 글을 확인한 뒤 자소서에 붙여 넣으십시오.`)
  }

  // 409 = 제안을 받은 뒤 글이 바뀌었다. 다시 검사하면 된다.
  const isStale = error?.status === 409
  useEffect(() => {
    if (isStale) setResult(null)
  }, [isStale])

  const replaceable = result?.suggestions.filter((s) => s.is_replacement) ?? []
  const guidance = result?.suggestions.filter((s) => !s.is_replacement) ?? []

  return (
    <section>
      <h1>글 다듬기</h1>
      <p className="muted">
        자소서 문항 하나를 붙여 넣고 검사하십시오. 맞춤법·띄어쓰기는 규칙으로 먼저 잡고,
        문장 다듬기는 AI가 제안합니다. 여기서는 저장하지 않습니다.
      </p>

      {error && (
        <p className="error">
          {isStale
            ? '글이 바뀌어 제안 위치가 맞지 않습니다. 다시 검사해 주십시오.'
            : `처리하지 못했습니다: ${error.message}`}
        </p>
      )}
      {done && <p className="success">{done}</p>}

      <div className="wr-grid">
        <div className="stack">
          <textarea
            className="wr-input"
            value={text}
            maxLength={MAX_TEXT_LEN}
            onChange={(e) => changeText(e.target.value)}
            placeholder="자소서 문항 본문을 붙여 넣으십시오."
            aria-label="자소서 본문"
          />
          <div className="row">
            <span className={isTooLong ? 'wr-count over grow' : 'wr-count grow'}>
              {text.length.toLocaleString()} / {MAX_TEXT_LEN.toLocaleString()}자
            </span>
            <button
              className="secondary"
              onClick={() => proofread(false)}
              disabled={isBusy || !text.trim()}
            >
              맞춤법만 검사
            </button>
            <button onClick={() => proofread(true)} disabled={isBusy || !text.trim()}>
              AI까지 검사
            </button>
          </div>
        </div>

        <div className="stack">
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
                  AI 응답이 안전 검사에서 걸러졌습니다({result.blocked_reason}). 규칙 검사
                  결과만 보여 드립니다.
                </p>
              )}

              {result.suggestions.length === 0 && (
                <p className="muted">고칠 곳을 찾지 못했습니다.</p>
              )}

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
                      <SuggestionItem
                        key={s.id}
                        item={s}
                        checked={accepted.has(s.id)}
                        onToggle={toggle}
                      />
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
                  <p className="muted">
                    무엇으로 바꿀지는 글쓴이만 알 수 있어 대안을 넣지 않았습니다.
                  </p>
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
      </div>
    </section>
  )
}
