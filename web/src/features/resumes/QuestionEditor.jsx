import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { resumesApi } from './api.js'
import DiffView from './DiffView.jsx'
import { BODY_MAX, LIMIT_STEP, clampLimit } from './limits.js'
import ShareTags from './ShareTags.jsx'

const MAX_VERSIONS = 50 // 서버 MAX_VERSIONS_PER_QUESTION과 같다(4.56)
import { experiencesApi } from '../experiences/api.js'
import { experienceSummary } from '../experiences/summary.js'

// 문항 편집: 저장할 때마다 새 버전(spec 3.1), 버전 타임라인, 두 버전 비교, 복원
export default function QuestionEditor({ resumeId, question, onSaved, onDelete, shareRev = 0 }) {
  const [body, setBody] = useState('')
  const [savedBody, setSavedBody] = useState('')
  const [limitInput, setLimitInput] = useState(String(question.char_limit ?? BODY_MAX))
  const composing = useRef(false) // 한글 등 입력기 조합 중
  const [blocked, setBlocked] = useState(false) // 글자수를 넘겨 입력이 잘렸는가
  const [versions, setVersions] = useState([])
  const [compare, setCompare] = useState({ from: '', to: '' })
  const [diff, setDiff] = useState(null)
  const [notice, setNotice] = useState(null)
  const [error, setError] = useState(null)
  const [experiences, setExperiences] = useState([])
  const [linked, setLinked] = useState([])
  const [pick, setPick] = useState('')
  const [showEnded, setShowEnded] = useState(false)

  const loadVersions = useCallback(async () => {
    const list = await resumesApi.listVersions(resumeId, question.id, showEnded)
    setVersions(list)
    return list
  }, [resumeId, question.id, showEnded])

  // 버전 목록(공유 태그 포함): 지난 공유 토글·공유 변경 때마다 다시 불러온다. 편집 중인 본문은 건드리지 않는다
  useEffect(() => {
    loadVersions().catch((e) => setError(e.message))
  }, [loadVersions, shareRev])

  // 본문 초기값: 문항이 바뀔 때만 최신 버전으로
  useEffect(() => {
    resumesApi
      .listVersions(resumeId, question.id)
      .then(async (list) => {
        if (list.length) {
          const latest = await resumesApi.getVersion(resumeId, question.id, list[0].id)
          setBody(latest.body)
          setSavedBody(latest.body)
        }
      })
      .catch((e) => setError(e.message))
  }, [resumeId, question.id])

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
    setNotice(null)
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

  const removeVersion = async (v) => {
    if (!window.confirm(`v${v.version_no}을(를) 삭제할까요? 되돌릴 수 없습니다.`)) return
    try {
      await resumesApi.removeVersion(resumeId, question.id, v.id)
      await loadVersions()
      onSaved()
      setError(null)
    } catch (e) {
      setError(e.message) // 지원 기록·공유 중이면 서버 안내 문구
    }
  }

  const showDiff = async () => {
    try {
      setDiff(await resumesApi.diff(resumeId, question.id, compare.from, compare.to))
    } catch (e) {
      setError(e.message)
    }
  }

  // 예전 문항(글자수 미설정)은 상한 10,000자로 본다
  const limit = question.char_limit ?? BODY_MAX
  // 글자수를 줄여 기존 본문이 넘친 경우 — 지우지 않고 저장만 막는다. 한글 조합 중 잠깐 1자 넘는 것은 경고하지 않는다
  const over = body.length > limit && !composing.current
  // 경고는 설정 글자수를 '넘기려 해서 잘렸을 때'만(정확히 도달한 것은 정상, 10/28). 글자수 아래로 내려가면 사라진다
  const atLimit = blocked && body.length >= limit
  // 새로 늘어난 부분만 잘라 낸다. 글자수를 줄여 이미 넘친 본문은 지우지 않는다(위 over 경고)
  const cut = (v) => {
    if (v.length > limit && v.length > body.length) {
      setBlocked(true)
      return v.slice(0, Math.max(limit, body.length))
    }
    if (v.length < limit) setBlocked(false)
    return v
  }

  const saveLimit = async (raw) => {
    const next = clampLimit(raw, limit)
    setLimitInput(String(next))
    if (next === question.char_limit) return
    try {
      await resumesApi.updateQuestion(resumeId, question.id, { char_limit: next })
      onSaved()
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="editor">
      <div className="row">
        <h2 className="grow">{question.title}</h2>
        {/* A6 리라이팅: 고른 후보를 이 문항의 새 버전으로 저장할 수 있게 자소서·문항 ID를 넘긴다(A 요청 10/28) */}
        <Link to={`/writing?${new URLSearchParams({ resume: resumeId, question: question.id })}`}>글 다듬기</Link>
        <button className="danger" onClick={onDelete}>
          문항 삭제
        </button>
      </div>
      {/* 설정 글자수에서 더 입력되지 않는다(붙여넣기도 잘림, 10/28).
          maxLength를 쓰지 않는다 — 한글 조합 중인 글자를 미리 세서 999자에서 멈춘다. 조합이 끝난 뒤 자른다 */}
      <textarea
        rows={12}
        value={body}
        onChange={(e) => setBody(composing.current ? e.target.value : cut(e.target.value))}
        onCompositionStart={() => (composing.current = true)}
        onCompositionEnd={(e) => {
          composing.current = false
          setBody(cut(e.currentTarget.value))
        }}
        aria-label="본문"
      />
      <div className="row">
        <span className={over || atLimit ? 'error' : 'muted'}>
          {body.length.toLocaleString()} / {limit.toLocaleString()}자 (공백 포함)
        </span>
        <label className="muted limit-field">
          글자 수 제한
          <input
            type="number"
            min="0" // 화살표가 100 단위(0 기준)로 움직이게. 0·빈 값은 clampLimit이 보정
            max={BODY_MAX}
            step={LIMIT_STEP}
            value={limitInput}
            onChange={(e) => setLimitInput(e.target.value)}
            onBlur={(e) => saveLimit(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
            aria-label="글자 수 제한"
          />
          자
        </label>
        <button onClick={save} disabled={body === savedBody || over}>
          새 버전으로 저장
        </button>
      </div>
      {body !== savedBody && <p className="muted">저장하지 않은 수정이 있습니다. 글 다듬기로 가기 전에 저장해 주세요.</p>}
      {atLimit && <p className="error">설정한 글자 수({limit.toLocaleString()}자)를 넘어 더 입력할 수 없습니다.</p>}
      {over && (
        <p className="error">
          설정한 글자 수보다 {(body.length - limit).toLocaleString()}자 많습니다. 줄인 뒤 저장해 주세요.
        </p>
      )}
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
              <span className="grow">{e.title}</span>
              <button className="secondary" onClick={() => unlinkExperience(e.id)}>
                연결 해제
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="row">
        <h3 className="grow">
          버전 기록 <span className="muted">{versions.length}/{MAX_VERSIONS}</span>
        </h3>
        <label className="muted share-toggle">
          <input type="checkbox" checked={showEnded} onChange={(e) => setShowEnded(e.target.checked)} />
          지난 공유 보기
        </label>
      </div>
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
            <ShareTags shares={v.shares} />
            {v !== versions[0] && (
              <button className="secondary" onClick={() => restore(v.id)}>
                이 버전으로 복원
              </button>
            )}
            <button className="danger" onClick={() => removeVersion(v)}>
              삭제
            </button>
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
