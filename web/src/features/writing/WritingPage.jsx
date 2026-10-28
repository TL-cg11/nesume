// 글 다듬기 — A6·A7·A13·A14 를 한 화면에 묶었다.
//
// ★ 탭은 **할 일** 기준 둘이다 (2026-10-28 개편, 이전에는 기능 기준 넷).
//     검사·교정  맞춤법·STAR(A7)와 글자 수·문체(A13)를 버튼 한 번으로 같이 본다.
//                두 검사는 같은 글의 같은 "고칠 곳" 을 찾는 일이라 나눌 이유가 없었다.
//     다시 쓰기  고른 구간을 AI 가 다시 쓴다(A6). 내 말투(A14)는 이 탭 안에 둔다 —
//                말투 프로필을 쓰는 곳이 리라이팅뿐이다.
//
// ★ 글자 수 제한·목표 문체는 **페이지 조건**이다. 문항 하나의 조건이라 두 탭이 같이 쓴다.
//
// ★ 글이나 조건이 바뀌면 결과를 버린다. 제안에는 위치(start/end)가 들어 있어
//   글이 바뀌면 맞지 않고, 조건이 바뀌면 판정이 달라진다.
//
// 저장하지 않는다. 다듬은 글은 사용자가 복사해 자소서에 붙인다 — 문항 맥락
// (?resume=&question=)으로 들어온 경우에만 다시 쓰기 후보를 새 버전으로 저장할 수 있다.
//
// 프론트 가이드(docs/dev/frontend-guide.md)를 따른다 — theme.css 변수만, 인라인 style 없음,
// 공용 클래스 우선, 기능 클래스는 wr- 접두사, 네 가지 상태 처리.

import { useCallback, useEffect, useRef, useState } from 'react'
import ReviewPanel from './ReviewPanel.jsx'
import RewritePanel from './RewritePanel.jsx'
import { MAX_TEXT_LEN, TONE_NAMES } from './api.js'
import './writing.css'

const TABS = [
  { id: 'review', label: '검사·교정', hint: '맞춤법·분량·문체·STAR 한 번에' },
  { id: 'rewrite', label: '다시 쓰기', hint: '고른 부분을 AI가 새로, 내 말투로' },
]

export default function WritingPage() {
  const [text, setText] = useState('')
  const [limit, setLimit] = useState('')
  const [tone, setTone] = useState('formal')
  const [tab, setTab] = useState('review')
  const [review, setReview] = useState(null)
  const [rewrite, setRewrite] = useState(null)
  // 다시 쓰기 탭이 보는 드래그 구간. 본문에서만 바뀐다
  const [selection, setSelection] = useState(null)
  const [isBusy, setIsBusy] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)
  const ctrlRef = useRef(null)

  // 화면을 떠날 때 진행 중인 요청을 취소한다 (가이드 5절)
  useEffect(() => () => ctrlRef.current?.abort(), [])

  const limitNum = Number(limit) || null
  const isOver = limitNum !== null && text.length > limitNum

  const clearResults = () => {
    setReview(null)
    setRewrite(null)
    setError(null)
  }

  const changeText = (v) => {
    setText(v)
    clearResults()
    setSelection(null)
    setDone(null)
  }

  const changeCondition = (setter) => (e) => {
    setter(e.target.value)
    setReview(null)
  }

  // 모든 패널이 쓰는 호출 래퍼. 취소·로딩·오류를 한곳에서 다룬다.
  //
  // ★ useCallback 으로 **고정**한다. 매 렌더마다 새 함수가 되면, 이것을 의존성으로
  //   쓰는 패널의 useEffect 가 렌더마다 다시 돌아 요청이 무한히 쌓인다.
  const run = useCallback(async (fn) => {
    ctrlRef.current?.abort()
    const ctrl = new AbortController()
    ctrlRef.current = ctrl
    setIsBusy(true)
    setError(null)
    setDone(null)
    try {
      return await fn(ctrl.signal)
    } catch (e) {
      if (e.name !== 'AbortError') setError(e)
      return null
    } finally {
      if (ctrlRef.current === ctrl) setIsBusy(false)
    }
  }, [])

  // 패널이 글을 바꿨을 때 (제안 반영·다시 쓴 글 채택)
  const applied = (next, message) => {
    setText(next)
    clearResults()
    setSelection(null)
    setDone(message)
  }

  const shared = { text, run, isBusy, onApplied: applied, tone }

  return (
    <section>
      <h1>글 다듬기</h1>
      <p className="muted">
        자소서 문항 하나를 붙여 넣으십시오. 검사하면 고칠 곳을 한 목록으로 보여 드리고,
        마음에 들지 않는 부분은 AI가 다시 써 드립니다. 여기서는 저장하지 않습니다.
      </p>

      {error && <p className="error">처리하지 못했습니다: {error.message}</p>}
      {done && <p className="success">{done}</p>}

      <div className="wr-grid">
        <div className="stack">
          <div className="row wr-conditions">
            <label className="wr-field">
              <span className="muted">글자 수 제한</span>
              <input
                type="number"
                min="1"
                value={limit}
                onChange={changeCondition(setLimit)}
                placeholder="없음"
                aria-label="글자 수 제한"
              />
            </label>
            <label className="wr-field">
              <span className="muted">목표 문체</span>
              <select value={tone} onChange={changeCondition(setTone)} aria-label="목표 문체">
                {Object.entries(TONE_NAMES).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
          </div>

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
          <div className="row">
            <span className={isOver ? 'wr-count over grow' : 'wr-count grow'}>
              {text.length.toLocaleString()}
              {limitNum ? ` / ${limitNum.toLocaleString()}자` : '자'}
              {isOver && ` · ${(text.length - limitNum).toLocaleString()}자 초과`}
            </span>
          </div>
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
            <ReviewPanel {...shared} limit={limitNum} result={review} setResult={setReview} />
          )}
          {tab === 'rewrite' && (
            <RewritePanel {...shared} selection={selection} result={rewrite} setResult={setRewrite} />
          )}
        </div>
      </div>
    </section>
  )
}
