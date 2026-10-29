import { useMemo, useState } from 'react'

// 버전 비교(10/29): 한 줄로 합친 보기. 같은 글은 그대로, 지운 글은 빨간 취소선, 추가한 글은 초록,
// 고친 글은 지운 글 바로 뒤에 새 글. 서버가 바뀐 단어 안을 글자 단위로 다시 나눠 준다(service.diff_segments).
// 문단 경계는 양쪽이 같은 부분(equal)의 줄바꿈으로 잡는다
function toParagraphs(segments) {
  const paras = [{ pieces: [], changed: false }]
  const cur = () => paras[paras.length - 1]
  segments.forEach((s, i) => {
    if (s.op === 'equal') {
      s.after.split('\n').forEach((text, j) => {
        if (j > 0) paras.push({ pieces: [], changed: false })
        if (text) cur().pieces.push({ key: `${i}-${j}`, text })
      })
      return
    }
    if (s.before) cur().pieces.push({ key: `${i}d`, text: s.before, mark: 'del' })
    if (s.after) cur().pieces.push({ key: `${i}i`, text: s.after, mark: 'ins' })
    cur().changed = true
  })
  return paras.filter((p) => p.pieces.length)
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
          v{diff.from_version} → v{diff.to_version}
          {' · '}
          <span className="diff2-added">추가 {added.toLocaleString()}자</span>
          {' · '}
          <span className="diff2-removed">삭제 {removed.toLocaleString()}자</span>
          {' · '}
          바뀐 문단 {changedCount}개
        </span>
        <span className="diff2-legend">
          <mark className="diff-del">지운 글</mark>
          <mark className="diff-ins">추가한 글</mark>
          <label className="muted">
            <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} /> 바뀐 문단만
          </label>
        </span>
      </div>
      {changedCount === 0 ? (
        <p className="muted">두 버전의 내용이 같습니다.</p>
      ) : (
        <div className="diff2-body">
          {rows.map((r) =>
            r.fold ? (
              <div key={r.key} className="diff2-fold">… 같은 문단 {r.count}개 …</div>
            ) : (
              <p key={r.key} className={`diff2-para${r.para.changed ? ' changed' : ''}`}>
                {r.para.pieces.map((p) =>
                  p.mark ? <mark key={p.key} className={`diff-${p.mark}`}>{p.text}</mark> : <span key={p.key}>{p.text}</span>,
                )}
              </p>
            ),
          )}
        </div>
      )}
    </div>
  )
}
