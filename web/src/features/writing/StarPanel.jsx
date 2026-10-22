// STAR 네 요소가 들어 있는지 보여준다.
//
// 요소 수로 AI 다듬기를 막지 않는다 (2026-10-22 팀 회의). 대신 빠진 요소를 그대로
// 보여주고, 제안 목록의 "직접 고쳐야 할 것" 에 보완 질문이 함께 올라간다.

const LABELS = { S: '상황', T: '과제', A: '행동', R: '결과' }
const ORDER = ['S', 'T', 'A', 'R']

export default function StarPanel({ star }) {
  if (!star) return null

  return (
    <div className="card wr-star">
      <strong>STAR 구성</strong>
      <div className="wr-star-marks">
        {ORDER.map((e) => (
          <span
            key={e}
            className={star.present.includes(e) ? 'wr-star-mark on' : 'wr-star-mark'}
            title={LABELS[e]}
          >
            {e}
          </span>
        ))}
      </div>

      {star.missing.length === 0 ? (
        <p className="muted">네 요소가 모두 들어 있습니다.</p>
      ) : (
        <p className="muted">빠진 요소: {star.missing_names.join(', ')}</p>
      )}
    </div>
  )
}
