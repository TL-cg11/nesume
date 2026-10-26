import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { mentorApi, roleError } from './api.js'
import { shortDate } from '../resumes/ShareTags.jsx'
import './share.css'

// B17 멘토: 받은 공유 목록(유효한 공유만)
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
      <h1>받은 공유</h1>
      <p className="muted">공유받은 자소서를 읽고 문단별로 코멘트를 남길 수 있습니다. 편집·다운로드는 할 수 없습니다.</p>
      {error && <p className="error">{error}</p>}
      {items && (
        <ul className="list share-view-list">
          {items.map((s) => (
            <li key={s.id}>
              <Link to={`/mentor/${s.id}`}>{s.resume_title}</Link>
              <span className="muted">{shortDate(s.end_date)}까지</span>
            </li>
          ))}
          {items.length === 0 && <li className="muted">받은 공유가 없습니다.</li>}
        </ul>
      )}
    </section>
  )
}
