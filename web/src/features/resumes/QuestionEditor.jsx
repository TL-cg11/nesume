import { useCallback, useEffect, useState } from 'react'
import { resumesApi } from './api.js'
import DiffView from './DiffView.jsx'
import { experiencesApi } from '../experiences/api.js'
import { experienceSummary } from '../experiences/summary.js'

// 문항 편집: 저장할 때마다 새 버전(spec 3.1), 버전 타임라인, 두 버전 비교, 복원
export default function QuestionEditor({ resumeId, question, onSaved, onDelete }) {
  const [body, setBody] = useState('')
  const [savedBody, setSavedBody] = useState('')
  const [versions, setVersions] = useState([])
  const [compare, setCompare] = useState({ from: '', to: '' })
  const [diff, setDiff] = useState(null)
  const [notice, setNotice] = useState(null)
  const [error, setError] = useState(null)
  const [experiences, setExperiences] = useState([])
  const [linked, setLinked] = useState([])
  const [pick, setPick] = useState('')

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

  const loadLinked = useCallback(
    () => experiencesApi.listLinked(resumeId, question.id).then(setLinked),
    [resumeId, question.id],
  )

  useEffect(() => {
    Promise.all([experiencesApi.list().then(setExperiences), loadLinked()]).catch((e) => setError(e.message))
  }, [loadLinked])

  // 경험 끌어오기: 본문 끝에 요약 한 문단 추가 + 문항↔경험 연결 기록(part2_guide 4.18, 4.22)
  const pullExperience = async () => {
    const e = experiences.find((x) => x.id === pick)
    if (!e) return
    try {
      await experiencesApi.link(resumeId, question.id, e.id)
      const summary = experienceSummary(e)
      setBody((cur) => (cur.trim() ? `${cur.replace(/\s+$/, '')}\n\n${summary}` : summary))
      setPick('')
      await loadLinked()
    } catch (err) {
      setError(err.message)
    }
  }

  const unlinkExperience = async (eid) => {
    try {
      await experiencesApi.unlink(resumeId, question.id, eid)
      await loadLinked()
    } catch (err) {
      setError(err.message)
    }
  }

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

      <h3>경험 끌어오기</h3>
      <div className="row">
        <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="끌어올 경험">
          <option value="">경험 선택</option>
          {experiences.map((e) => (
            <option key={e.id} value={e.id}>
              {e.title}
            </option>
          ))}
        </select>
        <button className="secondary" onClick={pullExperience} disabled={!pick}>
          본문에 추가
        </button>
        <span className="muted">본문 끝에 요약이 추가됩니다. 다듬은 뒤 저장하세요.</span>
      </div>
      {linked.length > 0 && (
        <ul className="timeline">
          {linked.map((e) => (
            <li key={e.id}>
              <span style={{ flex: 1 }}>{e.title}</span>
              <button className="secondary" onClick={() => unlinkExperience(e.id)}>
                연결 해제
              </button>
            </li>
          ))}
        </ul>
      )}

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
