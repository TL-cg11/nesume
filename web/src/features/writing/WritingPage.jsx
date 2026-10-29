// 글 다듬기 — 탭 둘.
//
//     검사·교정  맞춤법(A7)과 STAR 구성을 **따로** 검사한다. 둘 다 AI를 거친다 —
//                STAR 는 낱말 단서로는 "있다/없다" 밖에 못 보고, "결과는 있는데 숫자가 없다"
//                같은 부족함은 뜻을 읽어야 안다 (features/writing/star_review.py).
//     다시 쓰기  내가 평소 쓴 글(말투 샘플)을 넣으면 본문을 그 말투로 다시 쓴다 (A6).
//
// ★ 글이 바뀌면 결과를 버린다. 제안에는 위치(start/end)가 들어 있어 글이 바뀌면 맞지 않는다.
//
// 저장하지 않는다. 다듬은 글은 사용자가 복사해 자소서에 붙인다 — 문항 맥락
// (?resume=&question=)으로 들어온 경우에만 다시 쓰기 후보를 새 버전으로 저장할 수 있다.
//
// 프론트 가이드(docs/dev/frontend-guide.md)를 따른다 — theme.css 변수만, 인라인 style 없음,
// 공용 클래스 우선, 기능 클래스는 wr- 접두사, 네 가지 상태 처리.

import { useCallback, useEffect, useRef, useState } from 'react'
import ReviewPanel from './ReviewPanel.jsx'
import RewritePanel from './RewritePanel.jsx'
import { MAX_TEXT_LEN } from './api.js'
import './writing.css'

const TABS = [
  { id: 'review', label: '검사·교정', hint: '맞춤법과 STAR 구성' },
  { id: 'rewrite', label: '다시 쓰기', hint: '내가 쓴 글의 말투로' },
]

// 게이트웨이 오류(502 등)는 본문이 nginx HTML 이다. 그대로 띄우면 사용자는 코드 조각을 본다
function errorText(e) {
  if (e.status >= 500 && (!e.message || e.message.trimStart().startsWith('<'))) {
    return `서버에 잠시 연결하지 못했습니다(${e.status}). 잠시 후 다시 시도해 주십시오.`
  }
  return e.message
}

export default function WritingPage() {
  const [text, setText] = useState('')
  const [tab, setTab] = useState('review')
  const [spelling, setSpelling] = useState(null)
  const [star, setStar] = useState(null)
  const [rewrite, setRewrite] = useState(null)
  // 말투 샘플은 탭을 오가도 남긴다. 저장하지는 않는다
  const [sample, setSample] = useState('')
  // 다시 쓰기 탭이 보는 드래그 구간. 본문에서만 바뀐다
  const [selection, setSelection] = useState(null)
  const [busy, setBusy] = useState({})
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)
  const ctrls = useRef({})

  // 화면을 떠날 때 진행 중인 요청을 모두 취소한다 (가이드 5절)
  useEffect(() => () => Object.values(ctrls.current).forEach((c) => c.abort()), [])

  const clearResults = () => {
    setSpelling(null)
    setStar(null)
    setRewrite(null)
    setError(null)
  }

  const changeText = (v) => {
    setText(v)
    clearResults()
    setSelection(null)
    setDone(null)
  }

  // 모든 패널이 쓰는 호출 래퍼. 취소·로딩·오류를 한곳에서 다룬다.
  //
  // ★ 요청을 **이름별로** 따로 둔다. 맞춤법 검사 중에 STAR 검사를 눌러도 앞의 것이
  //   끊기지 않는다. 같은 이름을 다시 누르면 앞의 것만 취소한다.
  // ★ useCallback 으로 **고정**한다. 매 렌더마다 새 함수가 되면, 이것을 의존성으로
  //   쓰는 패널의 useEffect 가 렌더마다 다시 돌아 요청이 무한히 쌓인다.
  const run = useCallback(async (key, fn) => {
    ctrls.current[key]?.abort()
    const ctrl = new AbortController()
    ctrls.current[key] = ctrl
    setBusy((b) => ({ ...b, [key]: true }))
    setError(null)
    setDone(null)
    try {
      return await fn(ctrl.signal)
    } catch (e) {
      if (e.name !== 'AbortError') setError(e)
      return null
    } finally {
      if (ctrls.current[key] === ctrl) setBusy((b) => ({ ...b, [key]: false }))
    }
  }, [])

  // 패널이 글을 바꿨을 때 (제안 반영·다시 쓴 글 채택)
  const applied = (next, message) => {
    setText(next)
    clearResults()
    setSelection(null)
    setDone(message)
  }

  return (
    <section>
      <h1>글 다듬기</h1>
      <p className="muted">
        자소서 문항 하나를 붙여 넣으십시오. 맞춤법과 STAR 구성을 검사하고, 내가 쓴 글의
        말투로 다시 써 드립니다. 여기서는 저장하지 않습니다.
      </p>

      {error && <p className="error">처리하지 못했습니다: {errorText(error)}</p>}
      {done && <p className="success">{done}</p>}

      <div className="wr-grid">
        <div className="stack">
          <textarea
            className="wr-input"
            value={text}
            maxLength={MAX_TEXT_LEN}
            onChange={(e) => changeText(e.target.value)}
            // 드래그한 구간을 다시 쓰기 탭이 쓴다. 마우스·키보드 양쪽에서 같은 이벤트가 온다
            onSelect={(e) =>
              setSelection({ start: e.target.selectionStart, end: e.target.selectionEnd })
            }
            placeholder="자소서 문항 본문을 붙여 넣으십시오."
            aria-label="자소서 본문"
          />
          <span className="wr-count">
            {text.length.toLocaleString()} / {MAX_TEXT_LEN.toLocaleString()}자
          </span>
        </div>

        <div className="stack">
          <div className="wr-tabs" role="tablist" aria-label="작업 종류">
            {TABS.map((t) => (
              <button
                key={t.id}
                role="tab"
                aria-selected={tab === t.id}
                className={tab === t.id ? 'wr-tab on' : 'wr-tab'}
                onClick={() => setTab(t.id)}
              >
                {t.label}
                <span className="wr-tab-hint">{t.hint}</span>
              </button>
            ))}
          </div>

          {tab === 'review' && (
            <ReviewPanel
              text={text}
              run={run}
              busy={busy}
              onApplied={applied}
              spelling={spelling}
              setSpelling={setSpelling}
              star={star}
              setStar={setStar}
            />
          )}
          {tab === 'rewrite' && (
            <RewritePanel
              text={text}
              run={run}
              isBusy={Boolean(busy.rewrite)}
              onApplied={applied}
              selection={selection}
              sample={sample}
              setSample={setSample}
              result={rewrite}
              setResult={setRewrite}
            />
          )}
        </div>
      </div>
    </section>
  )
}
