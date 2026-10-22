// A7 — 맞춤법·문장 개선 + STAR 보완 화면 (tasks.md A7)
//
// 저장하지 않는다. 다듬은 글은 사용자가 복사해 자소서에 붙인다.
// 버전 저장은 B4 경로를 쓸 예정이고 source 값 규약을 B와 협의 중이다 (2026-10-22).

import { useState } from 'react'
import { MAX_TEXT_LEN, writingApi } from './api.js'
import StarPanel from './StarPanel.jsx'
import SuggestionItem from './SuggestionItem.jsx'
import '../resumes/resumes.css'
import './writing.css'

export default function WritingPage() {
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [accepted, setAccepted] = useState(() => new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)

  const tooLong = text.length > MAX_TEXT_LEN

  // 글이 바뀌면 이전 제안의 위치는 더 이상 맞지 않는다.
  // 서버도 409로 막지만, 화면에서 먼저 치워 두는 편이 덜 혼란스럽다.
  const onChangeText = (v) => {
    setText(v)
    if (result) setResult(null)
    setAccepted(new Set())
    setDone(null)
  }

  const run = async (useLlm) => {
    setBusy(true)
    setError(null)
    setDone(null)
    try {
      const body = await writingApi.proofread(text, useLlm)
      setResult(body)
      setAccepted(new Set())
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const toggle = (id) =>
    setAccepted((cur) => {
      const next = new Set(cur)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const applyAccepted = async () => {
    setBusy(true)
    setError(null)
    try {
      const body = await writingApi.apply(text, result.suggestions, [...accepted])
      setText(body.text)
      setResult(null)
      setAccepted(new Set())
      setDone(`${body.applied}건을 반영했습니다. 바뀐 글을 확인한 뒤 자소서에 붙여 넣으십시오.`)
    } catch (e) {
      // 409 = 제안을 받은 뒤 글이 바뀌었다. 다시 검사하면 된다.
      setError(
        e.status === 409
          ? '글이 바뀌어 제안 위치가 맞지 않습니다. 다시 검사해 주십시오.'
          : e.message,
      )
      if (e.status === 409) setResult(null)
    } finally {
      setBusy(false)
    }
  }

  const replaceable = result?.suggestions.filter((s) => s.is_replacement) ?? []
  const guidance = result?.suggestions.filter((s) => !s.is_replacement) ?? []

  return (
    <section>
      <h1>글 다듬기</h1>
      <p className="muted">
        자소서 문항 하나를 붙여 넣고 검사하십시오. 맞춤법·띄어쓰기는 규칙으로 먼저 잡고,
        문장 다듬기는 AI가 제안합니다. 여기서는 저장하지 않습니다.
      </p>

      {error && <p className="error">{error}</p>}
      {done && <p className="notice">{done}</p>}

      <div className="writing-grid">
        <div className="stack">
          <textarea
            value={text}
            onChange={(e) => onChangeText(e.target.value)}
            placeholder="자소서 문항 본문을 붙여 넣으십시오."
            aria-label="자소서 본문"
          />
          <div className="row">
            <span className={`char-count${tooLong ? ' over' : ''}`} style={{ flex: 1 }}>
              {text.length.toLocaleString()} / {MAX_TEXT_LEN.toLocaleString()}자
            </span>
            <button onClick={() => run(false)} disabled={busy || !text.trim() || tooLong}>
              맞춤법만 검사
            </button>
            <button onClick={() => run(true)} disabled={busy || !text.trim() || tooLong}>
              {busy ? '검사 중…' : 'AI까지 검사'}
            </button>
          </div>
        </div>

        <div className="stack">
          {!result && <p className="muted">검사하면 결과가 여기에 나옵니다.</p>}

          {result && (
            <>
              <StarPanel star={result.star} />

              {result.llm_unavailable && (
                <p className="notice">
                  AI 모델이 아직 연결되지 않아 규칙 검사만 했습니다.
                </p>
              )}
              {result.blocked_reason && (
                <p className="notice">
                  AI 응답이 안전 검사에서 걸러졌습니다({result.blocked_reason}).
                  규칙 검사 결과만 보여 드립니다.
                </p>
              )}

              {result.suggestions.length === 0 && (
                <p className="muted">고칠 곳을 찾지 못했습니다.</p>
              )}

              {replaceable.length > 0 && (
                <>
                  <div className="row">
                    <strong style={{ flex: 1 }}>고칠 곳 {replaceable.length}건</strong>
                    <button
                      onClick={() =>
                        setAccepted(new Set(replaceable.map((s) => s.id)))
                      }
                    >
                      모두 선택
                    </button>
                    <button onClick={() => setAccepted(new Set())}>선택 해제</button>
                  </div>
                  <ul className="suggestion-list">
                    {replaceable.map((s) => (
                      <SuggestionItem
                        key={s.id}
                        item={s}
                        checked={accepted.has(s.id)}
                        onToggle={toggle}
                      />
                    ))}
                  </ul>
                  <button onClick={applyAccepted} disabled={busy || accepted.size === 0}>
                    선택한 {accepted.size}건 반영
                  </button>
                </>
              )}

              {guidance.length > 0 && (
                <>
                  <strong>직접 고쳐야 할 것 {guidance.length}건</strong>
                  <p className="muted">
                    무엇으로 바꿀지는 글쓴이만 알 수 있어 대안을 넣지 않았습니다.
                  </p>
                  <ul className="suggestion-list">
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
