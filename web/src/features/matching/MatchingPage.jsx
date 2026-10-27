// 공고 매칭 — 공고 요건을 뽑아 내 자소서·경험과 대조한다 (tasks.md A11).
//
// ★ 저장하지 않는다. 분석만 한다 (schemas.py 머리말).
//
// ★ 왼쪽이 입력(공고 + 내 근거), 오른쪽이 결과다. 글 다듬기 화면과 달리 탭이 없다 —
//   여기서는 한 번의 분석이 한 가지 답을 낸다.
//
// ★ 이 화면이 보여주는 것의 핵심은 "지금 채울 수 있는 요건" 이다. 경험에는 있는데
//   자소서에 안 쓴 요건 — 지어내지 않고 채울 수 있는 유일한 칸이다.
//
// 프론트 가이드(docs/dev/frontend-guide.md)를 따른다 — theme.css 변수만, 인라인 style 없음,
// 공용 클래스 우선, 기능 클래스는 mt- 접두사, 네 가지 상태 처리.

import { useCallback, useEffect, useRef, useState } from 'react'
import EvidencePanel, { toExperienceIn } from './EvidencePanel.jsx'
import HintPanel from './HintPanel.jsx'
import MatchList from './MatchList.jsx'
import PostingForm from './PostingForm.jsx'
import { matchingApi } from './api.js'
import './matching.css'

const EMPTY_POSTING = {
  title: '',
  job_name: '',
  job_content: '',
  preferred: '',
  certificates: '',
  major: '',
  computer_skills: '',
}

// 공고 필드 중 하나라도 채워져 있어야 분석할 수 있다 (PostingIn `_not_all_empty`)
const hasAnyField = (posting) => Object.values(posting).some((v) => v.trim().length > 0)

export default function MatchingPage() {
  const [mode, setMode] = useState('paste')
  const [posting, setPosting] = useState(EMPTY_POSTING)
  const [postingId, setPostingId] = useState('')
  const [resumeText, setResumeText] = useState('')
  // null = 아직 안 불러옴. [] = 저장된 경험이 없음
  const [allExperiences, setAllExperiences] = useState(null)
  const [picked, setPicked] = useState(new Set())
  const [useLlm, setUseLlm] = useState(true)
  const [result, setResult] = useState(null)
  const [isBusy, setIsBusy] = useState(false)
  const [error, setError] = useState(null)
  const ctrlRef = useRef(null)

  // 화면을 떠날 때 진행 중인 요청을 취소한다 (가이드 5절)
  useEffect(() => () => ctrlRef.current?.abort(), [])

  // ★ useCallback 으로 고정한다. 매 렌더마다 새 함수가 되면 이것을 의존성으로 쓰는
  //   패널의 useEffect 가 렌더마다 다시 돌아 요청이 무한히 쌓인다 (글 다듬기 화면에서
  //   실제로 겪었다). 안에서 쓰는 것은 setState 와 ref 뿐이라 의존성이 비어도 안전하다.
  const run = useCallback(async (fn) => {
    ctrlRef.current?.abort()
    const ctrl = new AbortController()
    ctrlRef.current = ctrl
    setIsBusy(true)
    setError(null)
    try {
      return await fn(ctrl.signal)
    } catch (e) {
      if (e.name === 'AbortError') return null
      setError(e)
      return null
    } finally {
      if (ctrlRef.current === ctrl) setIsBusy(false)
    }
  }, [])

  const canAnalyze = mode === 'saved' ? postingId.trim().length > 0 : hasAnyField(posting)

  const analyze = async () => {
    setResult(null)
    const data = await run((signal) =>
      matchingApi.analyze(
        {
          ...(mode === 'saved'
            ? { postingId: postingId.trim() }
            : { posting: Object.fromEntries(Object.entries(posting).map(([k, v]) => [k, v || null])) }),
          resumeText,
          experiences: toExperienceIn(allExperiences, picked),
          useLlm,
        },
        signal,
      ),
    )
    if (data) setResult(data)
  }

  return (
    <section>
      <div className="row">
        <h1 className="grow">공고 매칭</h1>
      </div>
      <p className="muted">
        공고에서 요건을 뽑아 자소서와 경험에 있는지 대조합니다. 없는 경험은 문장을 만들지 않고
        질문으로 돌려드립니다. 여기서는 저장하지 않습니다.
      </p>

      {error && <ErrorLine error={error} />}

      <div className="mt-grid">
        <div className="stack">
          <section className="card stack">
            <strong>1. 공고</strong>
            <PostingForm
              mode={mode}
              onModeChange={setMode}
              posting={posting}
              onChange={setPosting}
              postingId={postingId}
              onPostingIdChange={setPostingId}
            />
          </section>

          <section className="card stack">
            <strong>2. 내 자소서와 경험</strong>
            <EvidencePanel
              resumeText={resumeText}
              onResumeTextChange={setResumeText}
              all={allExperiences}
              setAll={setAllExperiences}
              picked={picked}
              onPickedChange={setPicked}
              isBusy={isBusy}
            />
          </section>

          <div className="row">
            <label className="row grow">
              <input
                type="checkbox"
                checked={useLlm}
                onChange={(e) => setUseLlm(e.target.checked)}
              />
              <span>문장 제안까지 받기 (AI 사용)</span>
            </label>
            <button onClick={analyze} disabled={isBusy || !canAnalyze}>
              {isBusy ? '분석 중...' : '분석하기'}
            </button>
          </div>
          {!canAnalyze && (
            <p className="muted">
              {mode === 'saved' ? '공고 ID 를 넣으십시오.' : '공고 내용을 한 칸이라도 채우십시오.'}
            </p>
          )}
        </div>

        <div className="stack">
          {isBusy && <p className="muted">불러오는 중...</p>}
          {!isBusy && !result && !error && (
            <p className="muted">공고를 넣고 분석하면 요건 대조 결과가 여기에 나옵니다.</p>
          )}
          {result && <Result data={result} useLlm={useLlm} />}
        </div>
      </div>
    </section>
  )
}

function ErrorLine({ error }) {
  // 404 는 "없는 공고" 와 "볼 권한이 없는 공고" 양쪽이다. 구분해 쓰지 않는다
  // (가이드 9절 — 존재 노출 금지).
  if (error.status === 404) return <p className="error">공고를 찾을 수 없습니다.</p>
  if (error.status === 422) {
    return <p className="error">이 공고에는 분석할 본문·요건이 없습니다.</p>
  }
  if (error.status === 403) {
    return <p className="error">요청하신 자료는 현재 권한으로 열람할 수 없습니다.</p>
  }
  return <p className="error">분석하지 못했습니다: {error.message}</p>
}

function Result({ data, useLlm }) {
  const { counts, required_rate: rate, rate_reliable: reliable } = data

  return (
    <div className="stack">
      <section className="card mt-summary">
        <div className="row">
          <strong className="grow">요건 {data.matches.length}개</strong>
          {/* ★ 키워드가 적으면 비율이 요동친다. 서버가 못 믿겠다고 하면 숫자를 감춘다
              (coverage.py `rate_reliable`) — 틀린 숫자는 없는 숫자보다 나쁘다 */}
          {rate !== null && reliable && (
            <span className="mt-rate">필수 요건 달성 {Math.round(rate * 100)}%</span>
          )}
        </div>
        {rate !== null && !reliable && (
          <p className="muted">요건이 적어 달성률은 보여주지 않습니다.</p>
        )}
        {rate === null && <p className="muted">이 공고에서 필수 요건을 찾지 못했습니다.</p>}
        <ul className="list">
          <li>지금 채울 수 있는 요건 {counts.in_experience_only ?? 0}개</li>
          <li>근거가 없는 요건 {counts.missing ?? 0}개</li>
          <li>이미 쓴 요건 {counts.covered ?? 0}개</li>
        </ul>
      </section>

      {/* 차단 안내는 spec 9.1 문구를 그대로 쓴다. 어느 규칙에 걸렸는지는 보여주지 않는다 —
          탐지 내용을 알려 주면 그걸 피해 다시 넣을 수 있다 */}
      {data.blocked_reason && <p className="error">해당 요청은 처리할 수 없습니다.</p>}

      {data.posting_flags.length > 0 && (
        <p className="notice">
          공고 본문에 지시문처럼 보이는 내용이 있어 그 부분은 지시로 받지 않고 글자로만
          읽었습니다.
        </p>
      )}
      {data.posting_truncated && (
        <p className="notice">공고가 길어 뒷부분은 분석하지 않았습니다.</p>
      )}
      {useLlm && data.llm_unavailable && (
        <p className="notice">
          AI 를 쓸 수 없어 규칙 대조만 했습니다. 요건 목록은 그대로 쓸 수 있습니다.
        </p>
      )}

      <MatchList matches={data.matches} />

      <HintPanel
        hints={data.hints}
        questions={data.questions}
        notice={data.notice}
        droppedHints={data.dropped_hints}
      />
    </div>
  )
}
