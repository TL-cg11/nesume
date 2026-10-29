import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { mentorApi, roleError } from './api.js'
import { shortDate } from '../resumes/ShareTags.jsx'
import './share.css'

// B17 멘토: 받은 공유 목록(유효한 공유만). 10/29: 작성자 자소서 목록과 같은 카드 양식, 행 전체 클릭, 누가 공유했는지 표시
export default function MentorSharesPage() {
  const [items, setItems] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    mentorApi
      .list()
      .then(setItems)
      .catch((e) => setError(roleError(e)))
  }, [])

  return (
    <section>
      <h1>
        받은 공유 {items && <span className="muted">{items.length}</span>}
      </h1>
      <p className="muted">공유받은 자소서를 읽고 문단별로 코멘트를 남길 수 있습니다. 편집·다운로드는 할 수 없습니다.</p>
      {error && <p className="error">{error}</p>}
      {items === null && !error && <p className="muted">불러오는 중...</p>}
      {items?.length === 0 && (
        <div className="card share-view-empty">
          <p>받은 공유가 없습니다.</p>
          <p className="muted">작성자가 이 계정 이메일로 공유하면 여기에 보입니다.</p>
        </div>
      )}
      {items?.length > 0 && (
        <div className="card share-view-card">
          <ul className="list share-view-list">
            {items.map((s) => (
              <li key={s.id}>
                <div className="share-view-main">
                  {/* 제목 링크가 행 전체를 덮는다 → 빈 곳을 눌러도 열람 */}
                  <Link to={`/mentor/${s.id}`}>{s.resume_title}</Link>
                  <span className="muted share-view-from">
                    {s.owner_email ?? '작성자 정보 없음'}
                    {s.shared_at && ` · ${shortDate(s.shared_at.slice(0, 10))} 공유`}
                  </span>
                </div>
                <span className="muted">{shortDate(s.end_date)}까지</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
