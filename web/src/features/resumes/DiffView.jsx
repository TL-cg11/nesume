// 단어 단위 차이 표시. 삭제는 취소선, 추가는 강조.
export default function DiffView({ diff }) {
  return (
    <div className="diff" aria-label={`v${diff.from_version}과 v${diff.to_version} 비교`}>
      {diff.segments.map((s, i) => {
        if (s.op === 'equal') return <span key={i}>{s.after}</span>
        return (
          <span key={i}>
            {s.before && <del>{s.before}</del>}
            {s.after && <ins>{s.after}</ins>}
          </span>
        )
      })}
    </div>
  )
}
