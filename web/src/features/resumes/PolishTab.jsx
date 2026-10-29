import { useEffect, useState } from 'react'
import WritingPage from '../writing/WritingPage.jsx'
import { resumesApi } from './api.js'

// 자소서 상세 '글 다듬기' 탭(10/29): 다듬을 문항·버전을 고르면 그 본문으로 A의 글 다듬기 화면(검사·교정, 다시 쓰기)을 연다.
// 기능은 A 화면 그대로. 다시 쓰기 결과의 '새 버전으로 저장'은 주소의 resume·question을 읽으므로(A6) 상위에서 넣어 준다
export default function PolishTab({ resumeId, questions, questionId, onQuestion }) {
  const [versions, setVersions] = useState([])
  const [versionId, setVersionId] = useState('')
  const [body, setBody] = useState(null) // null = 불러오는 중
  const [error, setError] = useState(null)
  const q = questions.find((x) => x.id === questionId)

  // 문항이 바뀌면 버전 목록을 받고 최신 버전을 고른다
  useEffect(() => {
    if (!questionId) return
    let alive = true
    setBody(null)
    resumesApi
      .listVersions(resumeId, questionId)
      .then((list) => {
        if (!alive) return
        setVersions(list)
        setVersionId(list[0]?.id ?? '')
        if (!list.length) setBody('')
      })
      .catch((e) => alive && setError(e.message))
    return () => { alive = false }
  }, [resumeId, questionId])

  // 버전을 고르면 그 본문을 불러온다
  useEffect(() => {
    if (!versionId) return
    let alive = true
    setBody(null)
    resumesApi
      .getVersion(resumeId, questionId, versionId)
      .then((v) => alive && setBody(v.body))
      .catch((e) => alive && setError(e.message))
    return () => { alive = false }
  }, [resumeId, questionId, versionId])

  if (!questions.length) return <p className="muted">문항을 먼저 추가해 주세요.</p>

  return (
    <div className="polish-tab">
      <div className="card polish-pick">
        <label>
          문항
          <select value={questionId ?? ''} onChange={(e) => onQuestion(e.target.value)} aria-label="다듬을 문항">
            {questions.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
          </select>
        </label>
        <label>
          버전
          <select value={versionId} onChange={(e) => setVersionId(e.target.value)} disabled={!versions.length}
            aria-label="다듬을 버전">
            {versions.length === 0 && <option value="">저장된 버전 없음</option>}
            {versions.map((v, i) => (
              <option key={v.id} value={v.id}>
                v{v.version_no}{i === 0 ? ' (최신)' : ''} · {v.char_count.toLocaleString()}자
              </option>
            ))}
          </select>
        </label>
        <p className="muted">
          고른 버전의 본문으로 시작합니다. 다시 쓰기에서 고른 문장은 &lsquo;{q?.title}&rsquo;의 새 버전으로 저장할 수 있습니다.
        </p>
      </div>
      {error && <p className="error">{error}</p>}
      {body === null && !error && <p className="muted">불러오는 중...</p>}
      {/* 버전이 바뀌면 새 본문으로 다시 연다(key) */}
      {body !== null && <WritingPage key={`${questionId}:${versionId}`} initialText={body} embedded />}
    </div>
  )
}
