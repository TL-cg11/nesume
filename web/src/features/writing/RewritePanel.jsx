// A6 리라이팅 — 고른 구간을 다시 쓴 후보 3개를 보여주고 하나를 고르게 한다.
//
// ★ 이 탭만 **고른 구간**을 다룬다. 다른 탭은 글 전체를 본다. 본문에서 드래그한
//   부분이 없으면 글 전체를 고른 것으로 친다 — 아무것도 안 고르고 누른 사용자가
//   "왜 안 되지" 로 멈추지 않게 한다.
//
// ★ 저장은 **문항 맥락이 있을 때만** 할 수 있다. 글 다듬기 화면은 원래 저장하지
//   않는 연습장이다. B4 자소서 화면에서 ?resume=&question= 을 달고 넘어오면
//   "새 버전으로 저장" 이 켜진다.
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import {
  CANDIDATE_COUNT,
  CHUNK_CHARS,
  LENGTH_NAMES,
  MAX_KEYWORDS,
  MAX_KEYWORD_LEN,
  MAX_SELECTION_LEN,
  TONE_NAMES,
  rewriteApi,
} from './api.js'

export default function RewritePanel({ text, selection, run, isBusy, onApplied }) {
  const [tone, setTone] = useState('formal')
  const [length, setLength] = useState('similar')
  const [keywordText, setKeywordText] = useState('')
  const [result, setResult] = useState(null)
  const [saved, setSaved] = useState(null)
  const [params] = useSearchParams()

  const resumeId = params.get('resume')
  const questionId = params.get('question')
  const canSave = Boolean(resumeId && questionId)

  // 드래그한 구간이 없으면 글 전체다
  const hasSelection = selection && selection.end > selection.start
  const target = hasSelection ? text.slice(selection.start, selection.end) : text
  const keywords = splitKeywords(keywordText)

  const tooLong = target.length > MAX_SELECTION_LEN
  const badKeyword = keywords.find((k) => k.length > MAX_KEYWORD_LEN)
  const canRun = target.trim().length > 0 && !tooLong && !badKeyword
    && keywords.length <= MAX_KEYWORDS

  const rewrite = async () => {
    setResult(null)
    setSaved(null)
    const data = await run((signal) =>
      rewriteApi.rewrite({ text: target, tone, length, keywords }, signal),
    )
    if (data) setResult(data)
  }

  // 후보를 본문에 넣는다. 고른 구간만 바꾸고 나머지는 그대로 둔다
  const replace = (body) => {
    const next = hasSelection
      ? text.slice(0, selection.start) + body + text.slice(selection.end)
      : body
    onApplied(next, '고른 후보로 바꿨습니다. 저장은 자소서 화면에서 하십시오.')
  }

  const save = async (body) => {
    const data = await run((signal) =>
      rewriteApi.apply({ resumeId, questionId, body }, signal),
    )
    if (data) setSaved(`새 버전으로 저장했습니다 (${data.char_count.toLocaleString()}자).`)
  }

  return (
    <div className="stack">
      <p className="muted">
        본문에서 다시 쓸 부분을 드래그하고 옵션을 고르십시오. 후보 {CANDIDATE_COUNT}개를
        만들어 드립니다. 고르기 전에는 본문이 바뀌지 않습니다.
      </p>

      <p className={hasSelection ? 'notice' : 'muted'}>
        {hasSelection
          ? `고른 구간 ${target.length.toLocaleString()}자를 다시 씁니다.`
          : '고른 구간이 없어 글 전체를 다시 씁니다.'}
        {target.length > CHUNK_CHARS && ` 길어서 ${Math.ceil(target.length / CHUNK_CHARS)}번에 나눠 보냅니다.`}
      </p>

      <div className="row">
        <label className="wr-field">
          <span>문체</span>
          <select value={tone} onChange={(e) => setTone(e.target.value)}>
            {Object.entries(TONE_NAMES).map(([id, name]) => (
              <option key={id} value={id}>{name}</option>
            ))}
          </select>
        </label>
        <label className="wr-field">
          <span>길이</span>
          <select value={length} onChange={(e) => setLength(e.target.value)}>
            {Object.entries(LENGTH_NAMES).map(([id, name]) => (
              <option key={id} value={id}>{name}</option>
            ))}
          </select>
        </label>
      </div>

      <label className="stack">
        <span>넣고 싶은 말 (쉼표로 구분, {MAX_KEYWORDS}개까지)</span>
        <input
          value={keywordText}
          onChange={(e) => setKeywordText(e.target.value)}
          placeholder="협업, 데이터 분석, 리더십"
          aria-describedby="wr-kw-help"
        />
        <span id="wr-kw-help" className="muted">
          넣을 자리가 없으면 넣지 않습니다. 억지로 끼워 넣어 문장이 어색해지지 않게 합니다.
        </span>
      </label>

      {tooLong && (
        <p className="error">
          고른 구간이 {MAX_SELECTION_LEN.toLocaleString()}자를 넘습니다. 나눠서 고르십시오.
        </p>
      )}
      {badKeyword && (
        <p className="error">키워드 하나는 {MAX_KEYWORD_LEN}자까지입니다: {badKeyword.slice(0, 20)}</p>
      )}
      {keywords.length > MAX_KEYWORDS && (
        <p className="error">키워드는 {MAX_KEYWORDS}개까지 넣을 수 있습니다.</p>
      )}

      <div className="row">
        <button onClick={rewrite} disabled={isBusy || !canRun}>
          {isBusy ? '다시 쓰는 중...' : '후보 만들기'}
        </button>
      </div>

      {saved && <p className="success">{saved}</p>}

      {result && (
        <Result
          result={result}
          canSave={canSave}
          isBusy={isBusy}
          onReplace={replace}
          onSave={save}
        />
      )}
    </div>
  )
}

function Result({ result, canSave, isBusy, onReplace, onSave }) {
  return (
    <div className="stack">
      {result.notices.map((n) => (
        <p key={n} className="notice">{n}</p>
      ))}
      {/* 차단 안내는 spec 9.1 문구만 쓴다. 어느 규칙에 걸렸는지는 알려주지 않는다 —
          알려 주면 그걸 피해 다시 넣을 수 있다 */}
      {result.blocked_reason && <p className="error">해당 요청은 처리할 수 없습니다.</p>}
      {result.llm_unavailable && (
        <p className="notice">AI 를 쓸 수 없어 후보를 만들지 못했습니다.</p>
      )}

      {/* ★ 무엇이 모델에 갔는지 볼 수 있어야 한다 (A14 와 같은 생각) */}
      {result.instructions && (
        <details className="wr-fragment">
          <summary>모델에 보낸 지시문 보기</summary>
          <pre>{result.instructions}</pre>
        </details>
      )}

      {result.candidates.map((c) => (
        <section key={c.index} className="card wr-rewrite stack">
          <div className="row">
            <strong className="grow">후보 {c.index}</strong>
            <span className="muted">
              {c.char_count.toLocaleString()}자
              {' · '}
              {diffLabel(c.char_count, result.original_char_count)}
            </span>
          </div>

          <p>{c.body}</p>

          <details>
            <summary className="muted">원문과 달라진 곳</summary>
            <p>{c.segments.map((s, i) => <Segment key={i} seg={s} />)}</p>
          </details>

          <div className="row">
            <button onClick={() => onReplace(c.body)} disabled={isBusy}>
              이 후보로 바꾸기
            </button>
            {canSave && (
              <button onClick={() => onSave(c.body)} disabled={isBusy}>
                새 버전으로 저장
              </button>
            )}
          </div>
        </section>
      ))}

      {!canSave && result.candidates.length > 0 && (
        <p className="muted">
          자소서 화면에서 문항을 열고 넘어오면 고른 후보를 바로 새 버전으로 저장할 수 있습니다.
        </p>
      )}
    </div>
  )
}

// 변경 하이라이트. 색만으로 구분하지 않도록 취소선·굵기를 함께 준다 (가이드 10절)
function Segment({ seg }) {
  if (seg.op === 'equal') return <span>{seg.before}</span>
  return (
    <>
      {seg.before && <span className="wr-from">{seg.before}</span>}
      {seg.after && <span className="wr-to">{seg.after}</span>}
    </>
  )
}

function diffLabel(after, before) {
  const d = after - before
  if (d === 0) return '원문과 같은 길이'
  return d > 0 ? `${d.toLocaleString()}자 늘어남` : `${(-d).toLocaleString()}자 줄어듦`
}

// 쉼표로 자르고 앞뒤 공백과 빈 것을 없앤다. 중복은 서버가 한 번 더 없앤다
export function splitKeywords(value) {
  return value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}
