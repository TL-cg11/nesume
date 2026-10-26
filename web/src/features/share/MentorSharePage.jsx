import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { mentorApi, roleError } from './api.js'
import { shortDate } from '../resumes/ShareTags.jsx'
import './share.css'

const MAX_LEN = 1000

// B17 멘토: 공유된 자소서 읽기 전용 열람 + 문단별 코멘트(part2_guide 4.47)
// 개인정보는 '(전화번호 비공개)' 같은 문구로 표시된다(4.44).
export default function MentorSharePage() {
  const { shareId } = useParams()
  const [doc, setDoc] = useState(null)
  const [error, setError] = useState(null)
  const [draft, setDraft] = useState(null) // { key, version_id, paragraph_index, body, commentId? }

  const load = useCallback(
    () =>
      mentorApi
        .get(shareId)
        .then((d) => {
          setDoc(d)
          setError(null)
        })
        .catch((e) => setError(roleError(e))),
    [shareId],
  )

  useEffect(() => {
    load()
  }, [load])

  const save = async () => {
    try {
      if (draft.commentId) await mentorApi.editComment(shareId, draft.commentId, draft.body.trim())
      else
        await mentorApi.addComment(shareId, {
          version_id: draft.version_id,
          paragraph_index: draft.paragraph_index,
          body: draft.body.trim(),
        })
      setDraft(null)
      await load()
    } catch (e) {
      setError(roleError(e))
    }
  }

  const remove = async (cid) => {
    if (!window.confirm('코멘트를 삭제할까요?')) return
    try {
      await mentorApi.removeComment(shareId, cid)
      await load()
    } catch (e) {
      setError(roleError(e))
    }
  }

  if (error && !doc)
    return (
      <section>
        <p className="error">{error}</p>
        <Link to="/mentor">받은 공유로</Link>
      </section>
    )
  if (!doc) return <p className="muted">불러오는 중...</p>

  const editor = (
    <div className="stack">
      <textarea
        rows={3}
        value={draft?.body ?? ''}
        maxLength={MAX_LEN}
        onChange={(e) => setDraft({ ...draft, body: e.target.value })}
        aria-label="코멘트"
      />
      <div className="row">
        <span className="muted grow">{draft?.body.length ?? 0} / {MAX_LEN}자</span>
        <button onClick={save} disabled={!draft?.body.trim()}>
          저장
        </button>
        <button className="secondary" onClick={() => setDraft(null)}>
          취소
        </button>
      </div>
    </div>
  )

  return (
    <section>
      <div className="row">
        <h1 className="grow">{doc.resume_title}</h1>
        <span className="muted">{shortDate(doc.end_date)}까지 열람 가능</span>
      </div>
      <p className="muted">읽기 전용입니다. 문단마다 코멘트를 남길 수 있습니다.</p>
      {error && <p className="error">{error}</p>}

      {doc.questions.map((q) => (
        <article key={q.version_id} className="card share-view-question">
          <h2>{q.question_title}</h2>
          {q.char_limit && <p className="muted">{q.char_limit}자 제한</p>}
          {q.paragraphs.map((p, i) => {
            const key = `${q.version_id}:${i}`
            const cs = q.comments.filter((c) => c.paragraph_index === i)
            return (
              <div key={key} className="share-view-para">
                <p className="share-view-text">{p}</p>
                {cs.map((c) =>
                  draft?.commentId === c.id ? (
                    <div key={c.id}>{editor}</div>
                  ) : (
                    <div key={c.id} className="share-view-comment">
                      <p>{c.body}</p>
                      <div className="row">
                        <span className="muted grow">{new Date(c.updated_at).toLocaleString()}</span>
                        <button className="link" onClick={() => setDraft({ key, commentId: c.id, body: c.body })}>
                          수정
                        </button>
                        <button className="link" onClick={() => remove(c.id)}>
                          삭제
                        </button>
                      </div>
                    </div>
                  ),
                )}
                {draft?.key === key && !draft.commentId ? (
                  editor
                ) : (
                  <button
                    className="secondary share-view-add"
                    onClick={() => setDraft({ key, version_id: q.version_id, paragraph_index: i, body: '' })}
                  >
                    코멘트 남기기
                  </button>
                )}
              </div>
            )
          })}
          {q.paragraphs.length === 0 && <p className="muted">내용이 없습니다.</p>}
        </article>
      ))}
    </section>
  )
}
