// 요건 대조 결과 (A11). 상태별로 묶어 보여준다.
//
// ★ 묶는 순서는 서버 정렬과 같다 — 할 일이 있는 것부터다 (coverage.py `compare`).
//   "지금 채울 수 있는 요건"(경험엔 있고 자소서엔 없음)이 맨 위인 것이 이 화면의 핵심이다.
//
// ★ 상태를 색으로만 구분하지 않는다. 칸 이름과 기호를 함께 둔다 (가이드 10절).
import { CATEGORY_NAMES, FIELD_NAMES, IMPORTANCE_NAMES, STATUS_VIEW } from './api.js'

const MARKS = { in_experience_only: '△', missing: '✕', covered: '✓' }

function MatchItem({ match }) {
  return (
    <li className="mt-match">
      <div className="head">
        <strong className="grow">{match.text}</strong>
        <span className={`mt-badge imp-${match.importance}`}>
          {IMPORTANCE_NAMES[match.importance] ?? match.importance}
        </span>
        <span className="mt-badge">{CATEGORY_NAMES[match.category] ?? match.category}</span>
        {/* 택일 묶음 — 같은 group 끼리 하나만 맞아도 필수가 충족된다 */}
        {match.group && <span className="mt-badge group">택일</span>}
      </div>

      {match.experiences.length > 0 && (
        <p className="muted">경험에서 찾음: {match.experiences.join(', ')}</p>
      )}
      {match.fields.length > 0 && (
        <p className="muted">
          공고 출처: {match.fields.map((f) => FIELD_NAMES[f] ?? f).join(', ')}
        </p>
      )}
    </li>
  )
}

export default function MatchList({ matches }) {
  return (
    <div className="stack">
      {STATUS_VIEW.map(({ id, label, hint, tone }) => {
        const rows = matches.filter((m) => m.status === id)
        if (rows.length === 0) return null
        return (
          <section key={id} className="card mt-group">
            <div className="row">
              <span className={`mt-mark ${tone}`} aria-hidden="true">
                {MARKS[id]}
              </span>
              <strong className="grow">
                {label} {rows.length}개
              </strong>
            </div>
            <p className="muted">{hint}</p>
            <ul className="list">
              {rows.map((m) => (
                <MatchItem key={`${m.text}-${m.status}`} match={m} />
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
