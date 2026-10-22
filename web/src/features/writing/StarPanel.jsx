// STAR 네 요소가 들어 있는지 보여준다.
//
// 요소가 2개 이하면 서버가 AI 변환을 돌리지 않는다 — 빈칸이 많은 글을 모델에 주면
// 없는 경험을 지어내기 때문이다. 화면에서도 그 이유를 밝혀 둔다.

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

      {!star.can_convert && (
        <p className="notice">
          요소가 {star.count}개뿐이라 AI 다듬기를 돌리지 않았습니다. 빈칸이 많은 글을
          AI에 맡기면 없는 경험을 지어내기 때문입니다. 아래 안내를 먼저 채워 주십시오.
        </p>
      )}
    </div>
  )
}
