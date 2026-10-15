import { useCallback, useEffect, useState } from 'react'
import { resumesApi } from './api.js'
import DiffView from './DiffView.jsx'

// 문항 편집: 저장할 때마다 새 버전(spec 3.1), 버전 타임라인, 두 버전 비교, 복원
export default function QuestionEditor({ resumeId, question, onSaved, onDelete }) {
  const [body, setBody] = useState('')
  const [savedBody, setSavedBody] = useState('')
  const [versions, setVersions] = useState([])
  const [compare, setCompare] = useState({ from: '', to: '' })
  const [diff, setDiff] = useState(null)
  const [notice, setNotice] = useState(null)
  const [error, setError] = useState(null)

  const loadVersions = useCallback(async () => {
    const list = await resumesApi.listVersions(resumeId, question.id)
    setVersions(list)
    return list
  }, [resumeId, question.id])

  useEffect(() => {
    loadVersions()
      .then(async (list) => {
        if (list.length) {
          const latest = await resumesApi.getVersion(resumeId, question.id, list[0].id)
          setBody(latest.body)
          setSavedBody(latest.body)
        }
      })
      .catch((e) => setError(e.message))
  }, [loadVersions, resumeId, question.id])

  const afterSave = async (v) => {
    setBody(v.body)
    setSavedBody(v.body)
    setNotice(v.over_limit ? '버전이 50개를 넘었습니다. 오래된 버전 정리 방식은 추후 제공됩니다.' : null)
    await loadVersions()
    onSaved()
  }

  const save = async () => {
    try {
      await afterSave(await resumesApi.saveVersion(resumeId, question.id, body))
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }

  const restore = async (vid) => {
    try {
      await afterSave(await resumesApi.restore(resumeId, question.id, vid))
    } catch (e) {
      setError(e.message)
    }
  }

  const showDiff = async () => {
    try {
      setDiff(await resumesApi.diff(resumeId, question.id, compare.from, compare.to))
    } catch (e) {
      setError(e.message)
    }
  }

  const limit = question.char_limit
  const over = limit && body.length > limit

  return (
    <div className="editor">
      <div className="row">
        <h2>{question.title}</h2>
        <button className="secondary" onClick={onDelete}>
          문항 삭제
        </button>
      </div>
      <textarea rows={12} value={body} onChange={(e) => setBody(e.target.value)} aria-label="본문" />
      <div className="row">
        <span className={over ? 'error' : 'muted'}>
          {body.length}
          {limit ? ` / ${limit}자` : '자'} (공백 포함)
        </span>
        <button onClick={save} disabled={body === savedBody}>
          새 버전으로 저장
        </button>
      </div>
      {notice && <p className="notice">{notice}</p>}
      {error && <p className="error">{error}</p>}

      <h3>버전 기록</h3>
      <ul className="timeline">
        {versions.map((v) => (
          <li key={v.id}>
            <strong>v{v.version_no}</strong>
            <span className="muted">
              {v.source === 'ai' ? 'AI' : '수동'}
              {v.restored_from && ` · v${versions.find((x) => x.id === v.restored_from)?.version_no ?? '?'}에서 복원`}
              {' · '}
              {v.char_count}자 · {new Date(v.created_at).toLocaleString()}
            </span>
            {v !== versions[0] && (
              <button className="secondary" onClick={() => restore(v.id)}>
                이 버전으로 복원
              </button>
            )}
          </li>
        ))}
        {versions.length === 0 && <li className="muted">저장된 버전이 없습니다.</li>}
      </ul>

      {versions.length >= 2 && (
        <>
          <h3>버전 비교</h3>
          <div className="row">
            {['from', 'to'].map((k) => (
              <select key={k} value={compare[k]} onChange={(e) => setCompare({ ...compare, [k]: e.target.value })}>
                <option value="">{k === 'from' ? '이전' : '이후'}</option>
                {versions.map((v) => (
                  <option key={v.id} value={v.version_no}>
                    v{v.version_no}
                  </option>
                ))}
              </select>
            ))}
            <button className="secondary" onClick={showDiff} disabled={!compare.from || !compare.to}>
              비교
            </button>
          </div>
          {diff && <DiffView diff={diff} />}
        </>
      )}
    </div>
  )
}
