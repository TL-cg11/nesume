// STAR 보완 팝업 — 빠지거나 약한 요소마다 "AI가 써 넣기" 와 "빼기(그대로 두기)" 를 고른다.
//
// ★ AI가 지어 쓴 내용은 실제 경험이 아닐 수 있다. 그래서 요소마다 **사용자가 허락해야**
//   쓰고, 아는 사실을 적으면 그것만 쓰게 한다(서버 star_complete). 빼기로 한 요소는
//   AI에게 "만들지 말라" 고 전하고, STAR 칸에서도 더 권하지 않는다.
//
// 브라우저 기본 <dialog> 를 모달로 연다 — 포커스 가두기·Esc 닫기를 브라우저가 해 준다.

import { useEffect, useRef, useState } from 'react'
import { MAX_HINT_LEN } from './api.js'

export default function StarFillDialog({ open, elements, onSubmit, onClose }) {
  const ref = useRef(null)
  const [choices, setChoices] = useState({})
  const [hints, setHints] = useState({})

  // 열 때마다 기본값으로: 없는 요소는 "AI가 작성", 약한 요소는 "AI가 보완"
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      setChoices(Object.fromEntries(elements.map((e) => [e.element, 'ai'])))
      setHints({})
      dialog.showModal()
    } else if (!open && dialog.open) {
      dialog.close()
    }
  }, [open, elements])

  const aiCount = elements.filter((e) => choices[e.element] === 'ai').length

  const submit = (ev) => {
    ev.preventDefault()
    const fill = elements
      .filter((e) => choices[e.element] === 'ai')
      .map((e) => ({
        element: e.element,
        mode: e.status === 'missing' ? 'write' : 'improve',
        hint: (hints[e.element] ?? '').trim(),
      }))
    // 빠진 요소를 "빼기" 로 고른 것만 omit 이다. 약한 요소의 "그대로 두기" 는 손대지 않을 뿐이다
    const omit = elements
      .filter((e) => e.status === 'missing' && choices[e.element] === 'skip')
      .map((e) => e.element)
    onSubmit({ fill, omit })
  }

  return (
    <dialog ref={ref} className="wr-dialog" onClose={onClose} aria-labelledby="wr-dialog-title">
      <form method="dialog" onSubmit={submit} className="stack">
        <h2 id="wr-dialog-title">STAR 요소를 보완할까요?</h2>
        <p className="muted">
          빠지거나 부족한 요소가 있습니다. 요소마다 AI가 써 넣을지, 그대로 둘지 고르십시오.
          실제 있었던 일을 적어 주면 AI는 그 내용만 씁니다.
        </p>

        <ul className="list">
          {elements.map((e) => {
            const missing = e.status === 'missing'
            const choice = choices[e.element]
            return (
              <li key={e.element} className="wr-fill-row">
                <div className="row">
                  <strong className="grow">{e.name}</strong>
                  <span className={missing ? 'wr-badge danger' : 'wr-badge check'}>
                    {missing ? '없음' : '부족'}
                  </span>
                </div>
                {e.comment && <p className="muted">{e.comment}</p>}
                <div className="row" role="radiogroup" aria-label={`${e.name} 처리 방법`}>
                  <label className="wr-choice">
                    <input
                      type="radio"
                      name={`fill-${e.element}`}
                      checked={choice === 'ai'}
                      onChange={() => setChoices((c) => ({ ...c, [e.element]: 'ai' }))}
                    />
                    {missing ? 'AI가 지어서 작성' : 'AI가 보완'}
                  </label>
                  <label className="wr-choice">
                    <input
                      type="radio"
                      name={`fill-${e.element}`}
                      checked={choice === 'skip'}
                      onChange={() => setChoices((c) => ({ ...c, [e.element]: 'skip' }))}
                    />
                    {missing ? '이 요소는 빼기' : '그대로 두기'}
                  </label>
                </div>
                {choice === 'ai' && (
                  <input
                    className="wr-hint"
                    value={hints[e.element] ?? ''}
                    maxLength={MAX_HINT_LEN}
                    onChange={(ev) => setHints((h) => ({ ...h, [e.element]: ev.target.value }))}
                    placeholder={e.question ?? '실제 있었던 일을 적어 주십시오 (선택)'}
                    aria-label={`${e.name} 참고할 실제 사실`}
                  />
                )}
              </li>
            )
          })}
        </ul>

        {aiCount > 0 && (
          <p className="notice">
            참고 사실 없이 AI가 쓴 내용은 실제 경험이 아닐 수 있습니다. 결과에서 표시된 부분을 사실과
            맞게 고쳐 주십시오 — 없는 경험은 면접에서 드러납니다.
          </p>
        )}

        <div className="row">
          <span className="grow" />
          <button type="button" className="secondary" onClick={() => ref.current?.close()}>
            취소
          </button>
          <button type="submit">{aiCount > 0 ? `AI로 ${aiCount}개 보완하기` : '선택 저장'}</button>
        </div>
      </form>
    </dialog>
  )
}
