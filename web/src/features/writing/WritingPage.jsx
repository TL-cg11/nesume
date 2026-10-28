// 글 다듬기 — A7·A13·A14 를 한 화면에 묶었다 (tasks.md A7·A13·A14).
//
// ★ 세 기능이 **같은 글**을 다룬다. 화면을 나누면 사용자가 같은 본문을 세 번 붙여 넣어야 한다.
//   그래서 본문은 이 페이지가 한 벌만 들고, 오른쪽 탭이 그 글을 각자 본다.
//
// ★ 글이 바뀌면 **모든 탭의 결과를 버린다.** 제안에는 위치(start/end)가 들어 있어
//   글이 바뀌면 맞지 않는다. 서버도 409 로 막지만 화면에서 먼저 치우는 편이 덜 혼란스럽다.
//
// 저장하지 않는다. 다듬은 글은 사용자가 복사해 자소서에 붙인다 — 버전 저장은 B4 경로를
// 쓸 예정이고 source 값 규약을 B 와 협의 중이다 (2026-10-22).
//
// 프론트 가이드(docs/dev/frontend-guide.md)를 따른다 — theme.css 변수만, 인라인 style 없음,
// 공용 클래스 우선, 기능 클래스는 wr- 접두사, 네 가지 상태 처리.

import { useCallback, useEffect, useRef, useState } from 'react'
import ProfilePanel from './ProfilePanel.jsx'
import ProofreadPanel from './ProofreadPanel.jsx'
import RewritePanel from './RewritePanel.jsx'
import StylePanel from './StylePanel.jsx'
import { MAX_TEXT_LEN } from './api.js'
import './writing.css'

const TABS = [
  { id: 'proofread', label: '맞춤법·STAR', hint: '틀린 곳과 빠진 요소' },
  { id: 'style', label: '글자수·문체', hint: '분량과 말투 통일' },
  { id: 'rewrite', label: '리라이팅', hint: '고른 부분을 다시 쓰기' },
  { id: 'profile', label: '내 말투', hint: 'AI 가 흉내 낼 문체' },
]

export default function WritingPage() {
  const [text, setText] = useState('')
  const [tab, setTab] = useState('proofread')
  const [proofreadResult, setProofreadResult] = useState(null)
  const [styleResult, setStyleResult] = useState(null)
  // 리라이팅 탭이 보는 드래그 구간. 본문에서만 바뀐다
  const [selection, setSelection] = useState(null)
  const [isBusy, setIsBusy] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)
  const ctrlRef = useRef(null)

  // 화면을 떠날 때 진행 중인 요청을 취소한다 (가이드 5절)
  useEffect(() => () => ctrlRef.current?.abort(), [])

  const isTooLong = text.length > MAX_TEXT_LEN

  const changeText = (v) => {
    setText(v)
    // 글이 바뀌면 두 탭의 제안이 모두 무효다
    setProofreadResult(null)
    setStyleResult(null)
    setSelection(null)
    setDone(null)
  }

  // 모든 패널이 쓰는 호출 래퍼. 취소·로딩·오류를 한곳에서 다룬다.
  // quiet404: "아직 없음"이 정상인 조회(A14 프로필)에서 404 를 오류로 띄우지 않는다.
  //
  // ★ useCallback 으로 **고정**한다. 매 렌더마다 새 함수가 되면, 이것을 의존성으로
  //   쓰는 패널의 useEffect 가 렌더마다 다시 돌아 요청이 무한히 쌓인다.
  //   (실제로 그렇게 만들었다가 브라우저에서 1만 9천 건이 나가는 것을 보고 고쳤다.)
  //   안에서 쓰는 것은 setState 와 ref 뿐이라 의존성이 비어도 안전하다.
  const run = useCallback(async (fn, { quiet404 = false } = {}) => {
    ctrlRef.current?.abort()
    const ctrl = new AbortController()
    ctrlRef.current = ctrl
    setIsBusy(true)
    setError(null)
    try {
      return await fn(ctrl.signal)
    } catch (e) {
      if (e.name === 'AbortError') return null
      if (quiet404 && e.status === 404) return null
      setError(e)
      return null
    } finally {
      if (ctrlRef.current === ctrl) setIsBusy(false)
    }
  }, [])

  // 패널이 글을 바꿨을 때 (제안 반영·다시 쓴 글 채택)
  const applied = (next, message) => {
    setText(next)
    setProofreadResult(null)
    setStyleResult(null)
    setDone(message)
  }

  // 409 = 제안을 받은 뒤 글이 바뀌었다. 다시 검사하면 된다.
  const isStale = error?.status === 409
  useEffect(() => {
    if (isStale) {
      setProofreadResult(null)
      setStyleResult(null)
    }
  }, [isStale])

  const shared = { text, run, isBusy, onApplied: applied }

  return (
    <section>
      <h1>글 다듬기</h1>
      <p className="muted">
        자소서 문항 하나를 붙여 넣으십시오. 맞춤법·분량·문체를 한자리에서 봅니다.
        여기서는 저장하지 않습니다.
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
            // 드래그한 구간을 리라이팅 탭이 쓴다. 마우스·키보드 양쪽에서 같은 이벤트가 온다
            onSelect={(e) =>
              setSelection({ start: e.target.selectionStart, end: e.target.selectionEnd })
            }
            placeholder="자소서 문항 본문을 붙여 넣으십시오."
            aria-label="자소서 본문"
          />
          <div className="row">
            <span className={isTooLong ? 'wr-count over grow' : 'wr-count grow'}>
              {text.length.toLocaleString()} / {MAX_TEXT_LEN.toLocaleString()}자
            </span>
          </div>
        </div>

        <div className="stack">
          <div className="wr-tabs" role="tablist" aria-label="검사 종류">
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

          {tab === 'proofread' && (
            <ProofreadPanel {...shared} result={proofreadResult} setResult={setProofreadResult} />
          )}
          {tab === 'style' && (
            <StylePanel {...shared} result={styleResult} setResult={setStyleResult} />
          )}
          {tab === 'rewrite' && <RewritePanel {...shared} selection={selection} />}
          {tab === 'profile' && <ProfilePanel text={text} run={run} isBusy={isBusy} />}
        </div>
      </div>
    </section>
  )
}
