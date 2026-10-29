// 다시 쓰기 — 내가 평소에 쓴 글(말투 샘플)을 넣으면 본문을 그 말투로 다시 쓴다 (A6).
//
// ★ 샘플은 **말투만** 빌린다. 샘플 속 사실·숫자는 가져오지 않는다 — 서버가 원문에 없는
//   숫자가 들어간 후보를 버린다 (rewrite_service). 샘플은 저장하지 않는다.
// ★ 문장 끝맺음(합니다체 등)은 따로 고른다. 블로그 글을 샘플로 넣어도 자소서는
//   합니다체로 남길 수 있게.
// ★ 본문에서 드래그한 부분이 없으면 글 전체를 다시 쓴다.
// ★ 저장은 **문항 맥락이 있을 때만** 할 수 있다. B4 자소서 화면에서
//   ?resume=&question= 을 달고 넘어오면 "새 버전으로 저장" 이 켜진다.
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import {
  CANDIDATE_COUNT,
  CHUNK_CHARS,
  MAX_SAMPLE_CHARS,
  MAX_SELECTION_LEN,
  MIN_SAMPLE_CHARS,
  TONE_NAMES,
  rewriteApi,
} from './api.js'

export default function RewritePanel({
  text, run, isBusy, onApplied, selection, sample, setSample, result, setResult,
}) {
  const [tone, setTone] = useState('formal')
  const [saved, setSaved] = useState(null)
  const [params] = useSearchParams()

  const resumeId = params.get('resume')
  const questionId = params.get('question')
  const canSave = Boolean(resumeId && questionId)

  // 드래그한 구간이 없으면 글 전체다
  const hasSelection = selection && selection.end > selection.start
  const target = hasSelection ? text.slice(selection.start, selection.end) : text

  const sampleLen = sample.trim().length
  const sampleShort = sampleLen < MIN_SAMPLE_CHARS
  const tooLong = target.length > MAX_SELECTION_LEN
  const canRun = target.trim().length > 0 && !tooLong && !sampleShort

  const rewrite = async () => {
    setResult(null)
    setSaved(null)
    // 후보를 고를 때 바꿀 자리를 기억해 둔다. 기다리는 동안 드래그가 바뀌어도
    // 후보는 **보낸 구간**에 들어가야 한다
    const range = hasSelection ? { ...selection } : null
    const data = await run('rewrite', (signal) =>
      rewriteApi.rewrite({ text: target, tone, styleSample: sample.trim() }, signal),
    )
    if (data) setResult({ ...data, range })
  }

  // 후보를 본문에 넣는다. 고른 구간만 바꾸고 나머지는 그대로 둔다
  const replace = (body) => {
    const { range } = result
    const next = range ? text.slice(0, range.start) + body + text.slice(range.end) : body
    onApplied(next, '고른 후보로 바꿨습니다. 저장은 자소서 화면에서 하십시오.')
  }

  const save = async (body) => {
    const data = await run('rewrite', (signal) =>
      rewriteApi.apply({ resumeId, questionId, body }, signal),
    )
    if (data) setSaved(`새 버전으로 저장했습니다 (${data.char_count.toLocaleString()}자).`)
  }

  return (
    <div className="stack">
      <label className="stack wr-sample-field">
        <strong>내 말투 샘플</strong>
        <span className="muted">
          평소에 내가 쓴 글을 붙여 넣으십시오(블로그·메모·다른 자소서 등). 어휘·문장 길이·연결
          표현을 이 글처럼 맞춥니다. 샘플의 내용과 숫자는 가져오지 않고, 저장하지 않습니다.
        </span>
        <textarea
          className="wr-sample"
          value={sample}
          maxLength={MAX_SAMPLE_CHARS}
          onChange={(e) => setSample(e.target.value)}
          placeholder="내가 쓴 글을 붙여 넣으십시오."
        />
        <span className={sampleShort && sampleLen > 0 ? 'wr-count over' : 'wr-count'}>
          {sampleLen.toLocaleString()} / {MAX_SAMPLE_CHARS.toLocaleString()}자
          {sampleShort && ` · ${MIN_SAMPLE_CHARS}자 이상 필요`}
        </span>
      </label>

      <p className={hasSelection ? 'notice' : 'muted'}>
        {hasSelection
          ? `본문에서 고른 ${target.length.toLocaleString()}자를 다시 씁니다.`
          : '본문에서 다시 쓸 부분을 드래그하십시오. 고르지 않으면 글 전체를 다시 씁니다.'}
        {target.length > CHUNK_CHARS && ` 길어서 ${Math.ceil(target.length / CHUNK_CHARS)}번에 나눠 보냅니다.`}
      </p>
      {tooLong && (
        <p className="error">
          고른 구간이 {MAX_SELECTION_LEN.toLocaleString()}자를 넘습니다. 나눠서 고르십시오.
        </p>
      )}

      <div className="row">
        <label className="wr-field">
          <span className="muted">문장 끝맺음</span>
          <select value={tone} onChange={(e) => setTone(e.target.value)}>
            {Object.entries(TONE_NAMES).map(([id, name]) => (
              <option key={id} value={id}>{name}</option>
            ))}
          </select>
        </label>
        <span className="grow" />
        <button onClick={rewrite} disabled={isBusy || !canRun}>
          {isBusy ? '다시 쓰는 중...' : `이 말투로 후보 ${CANDIDATE_COUNT}개 만들기`}
        </button>
      </div>

      {saved && <p className="success">{saved}</p>}

      {result && (
        <Result result={result} canSave={canSave} isBusy={isBusy} onReplace={replace} onSave={save} />
      )}
    </div>
  )
}

function Result({ result, canSave, isBusy, onReplace, onSave }) {
  return (
    <div className="stack">
      {/* "운영자 프롬프트 미등록" 은 사용자가 할 수 있는 일이 없는 운영 안내라 뺀다
          (rewrite_service._template_body). 형식 오류·후보 부족·숫자 제외 안내는 보여준다 */}
      {result.notices
        .filter((n) => !n.startsWith('운영자'))
        .map((n) => (
          <p key={n} className="notice">{n}</p>
        ))}
      {/* 차단 안내는 spec 9.1 문구만 쓴다. 어느 규칙에 걸렸는지는 알려주지 않는다 */}
      {result.blocked_reason && <p className="error">해당 요청은 처리할 수 없습니다.</p>}
      {result.llm_unavailable && (
        <p className="notice">AI를 쓸 수 없어 후보를 만들지 못했습니다. 잠시 후 다시 시도해 주십시오.</p>
      )}

      {result.candidates.map((c) => (
        <section key={c.index} className="card wr-rewrite stack">
          <div className="row">
            <strong className="grow">후보 {c.index}</strong>
            <span className="muted">
              {c.char_count.toLocaleString()}자 · {diffLabel(c.char_count, result.original_char_count)}
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
              <button className="secondary" onClick={() => onSave(c.body)} disabled={isBusy}>
                새 버전으로 저장
              </button>
            )}
          </div>
        </section>
      ))}

      {/* ★ 무엇이 모델에 갔는지 볼 수 있어야 한다 */}
      {result.instructions && (
        <details className="wr-fragment">
          <summary>모델에 보낸 지시문 보기</summary>
          <pre>{result.instructions}</pre>
        </details>
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
