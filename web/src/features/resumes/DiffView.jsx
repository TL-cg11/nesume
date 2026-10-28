import { useMemo, useState } from 'react'

// 버전 비교(10/28): 이전|이후 나란히, 문단 단위로 맞춤, 바뀐 단어만 옅게 칠함 + 변경 요약 + '바뀐 문단만' 접기.
// 서버는 단어 단위 조각(equal/delete/insert/replace)을 준다. 문단 경계는 양쪽이 같은 부분(equal)의 줄바꿈으로 잡는다
function toParagraphs(segments) {
  const paras = [{ left: [], right: [], changed: false }]
  const cur = () => paras[paras.length - 1]
  segments.forEach((s, i) => {
    if (s.op === 'equal') {
      const parts = s.after.split('\n')
      parts.forEach((text, j) => {
        if (j > 0) paras.push({ left: [], right: [], changed: false })
        if (text) {
          cur().left.push({ key: `${i}-${j}`, text })
          cur().right.push({ key: `${i}-${j}`, text })
        }
      })
      return
    }
    if (s.before) cur().left.push({ key: `${i}d`, text: s.before, mark: 'del' })
    if (s.after) cur().right.push({ key: `${i}i`, text: s.after, mark: 'ins' })
    cur().changed = true
  })
  return paras.filter((p) => p.left.length || p.right.length)
}

function Side({ pieces }) {
  if (!pieces.length) return <span className="muted">(없음)</span>
  return pieces.map((p) => (p.mark ? <mark key={p.key} className={`diff-${p.mark}`}>{p.text}</mark> : <span key={p.key}>{p.text}</span>))
}

export default function DiffView({ diff }) {
  const [onlyChanged, setOnlyChanged] = useState(true)
  const paras = useMemo(() => toParagraphs(diff.segments), [diff])
  const added = diff.segments.reduce((n, s) => n + (s.op === 'equal' ? 0 : s.after.length), 0)
  const removed = diff.segments.reduce((n, s) => n + (s.op === 'equal' ? 0 : s.before.length), 0)
  const changedCount = paras.filter((p) => p.changed).length

  // 바뀐 문단만 보기: 연속된 같은 문단은 한 줄로 접는다
  const rows = []
  paras.forEach((p, i) => {
    if (onlyChanged && !p.changed) {
      const last = rows[rows.length - 1]
      if (last?.fold) last.count += 1
      else rows.push({ fold: true, count: 1, key: `f${i}` })
    } else rows.push({ para: p, key: `p${i}` })
  })

  return (
    <div className="diff2" aria-label={`v${diff.from_version}과 v${diff.to_version} 비교`}>
      <div className="diff2-summary">
        <span>
          <span className="diff2-added">추가 {added.toLocaleString()}자</span>
          {' · '}
          <span className="diff2-removed">삭제 {removed.toLocaleString()}자</span>
          {' · '}
          바뀐 문단 {changedCount}개
        </span>
        <label className="muted">
          <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} /> 바뀐 문단만
        </label>
      </div>
      {changedCount === 0 ? (
        <p className="muted">두 버전의 내용이 같습니다.</p>
      ) : (
        <div className="diff2-grid">
          <div className="diff2-head">v{diff.from_version} (이전)</div>
          <div className="diff2-head">v{diff.to_version} (이후)</div>
          {rows.map((r) =>
            r.fold ? (
              <div key={r.key} className="diff2-fold">… 같은 문단 {r.count}개 …</div>
            ) : (
              <div key={r.key} className={`diff2-row${r.para.changed ? ' changed' : ''}`}>
                <div className="diff2-cell"><Side pieces={r.para.left} /></div>
                <div className="diff2-cell"><Side pieces={r.para.right} /></div>
              </div>
            ),
          )}
        </div>
      )}
    </div>
  )
}
