import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { resumesApi } from './api.js'
import DiffView from './DiffView.jsx'
import { BODY_MAX, LIMIT_STEP, clampLimit } from './limits.js'
import VersionList from './VersionList.jsx'

const MAX_VERSIONS = 50 // 서버 MAX_VERSIONS_PER_QUESTION과 같다(4.56)
import { experiencesApi } from '../experiences/api.js'
import { period } from '../experiences/summary.js'
import { TYPES, normalizeType } from '../experiences/templates.js'

// 문항 편집: 저장할 때마다 새 버전(spec 3.1), 버전 타임라인, 두 버전 비교, 복원
// tab: 'write'(작성) | 'versions'(버전 관리·비교). 탭을 바꿔도 같은 컴포넌트라 작성 중인 글이 유지된다(10/29)
export default function QuestionEditor({ resumeId, question, onSaved, onDelete, shareRev = 0, tab = 'write', onGoWrite }) {
  const [body, setBody] = useState('')
  const [savedBody, setSavedBody] = useState('') // 최신 저장 버전의 본문
  const [loaded, setLoaded] = useState(null) // 편집칸에 불러온 버전 { id, no, body } — 최신이면 최신 버전
  const [preview, setPreview] = useState(null) // 버전 탭에서 미리보는 버전 { id, no, body }
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
  const [pickType, setPickType] = useState('') // 경험 끌어오기: 유형 먼저
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
          setLoaded({ id: latest.id, no: latest.version_no, body: latest.body })
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

  const candidates = experiences.filter((e) => !linked.some((l) => l.id === e.id)) // 아직 연결 안 한 경험

  // 경험 끌어오기: 문항↔경험 연결만 기록한다. 연결한 경험은 AI가 참고할 자료이고 본문에는 넣지 않는다
  // (10/28 사용자 결정, part2_guide 4.65 — 4.22의 '본문 끝에 요약 추가'를 대체)
  const pullExperience = async () => {
    if (!pick) return
    try {
      await experiencesApi.link(resumeId, question.id, pick)
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
    setLoaded({ id: v.id, no: v.version_no, body: v.body })
    setNotice(null)
    await loadVersions()
    onSaved()
  }

  // 예전 버전을 불러와 고치지 않고 저장하면 '복원'(restored_from 기록), 고쳤으면 일반 저장(10/28)
  const save = async () => {
    try {
      const isRestore = loaded && loaded.id !== versions[0]?.id && body === loaded.body
      await afterSave(await (isRestore
        ? resumesApi.restore(resumeId, question.id, loaded.id)
        : resumesApi.saveVersion(resumeId, question.id, body)))
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }

  // 버전 기록 행 클릭: 그 버전 본문을 편집칸에 불러온다(복원 버튼 대신, 10/28). 저장 전 수정이 있으면 먼저 묻는다
  const openVersion = async (v) => {
    if (loaded?.id === v.id) return true
    if (body !== (loaded?.body ?? savedBody) && !window.confirm('저장하지 않은 수정이 있습니다. 불러오면 사라집니다. 계속할까요?')) return false
    try {
      const full = await resumesApi.getVersion(resumeId, question.id, v.id)
      setBody(full.body)
      setLoaded({ id: full.id, no: full.version_no, body: full.body })
      setNotice(v.id === versions[0]?.id ? null : `v${full.version_no}을(를) 불러왔습니다. 그대로 저장하면 이 버전으로 복원됩니다.`)
      setError(null)
      return true
    } catch (e) {
      setError(e.message)
      return false
    }
  }

  // 버전 탭: 행 클릭 = 미리보기(작성 중인 글은 그대로), '이 버전으로 작성 이어가기' = 불러와 작성 탭으로
  const selectPreview = async (v) => {
    try {
      const full = await resumesApi.getVersion(resumeId, question.id, v.id)
      setPreview({ id: full.id, no: full.version_no, body: full.body })
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }

  const continueFrom = async () => {
    if (await openVersion({ id: preview.id, version_no: preview.no })) onGoWrite?.()
  }

  const removeVersion = async (v) => {
    if (!window.confirm(`v${v.version_no}을(를) 삭제할까요? 되돌릴 수 없습니다.`)) return
    try {
      await resumesApi.removeVersion(resumeId, question.id, v.id)
      if (loaded?.id === v.id) setLoaded(null) // 보던 버전을 지웠으면 본문은 그대로 두고 표시만 해제
      if (preview?.id === v.id) setPreview(null)
      await loadVersions()
      onSaved()
      setError(null)
    } catch (e) {
      setError(e.message) // 지원 기록·공유 중이면 서버 안내 문구
    }
  }

  // 비교 기본값: 지금 보는 버전과 그 직전 버전(보는 게 가장 오래된 버전이면 그다음 버전과)
  useEffect(() => {
    if (versions.length < 2) return setDiff(null)
    const idx = Math.max(0, versions.findIndex((v) => v.id === (preview?.id ?? loaded?.id)))
    const to = versions[idx === versions.length - 1 ? idx - 1 : idx]
    const from = versions[idx === versions.length - 1 ? idx : idx + 1]
    setCompare({ from: String(from.version_no), to: String(to.version_no) })
  }, [versions, loaded?.id, preview?.id])

  // 두 버전을 고르면 바로 비교
  useEffect(() => {
    if (!compare.from || !compare.to || compare.from === compare.to) return setDiff(null)
    let alive = true
    resumesApi.diff(resumeId, question.id, compare.from, compare.to)
      .then((d) => alive && setDiff(d))
      .catch((e) => alive && setError(e.message))
    return () => { alive = false }
  }, [resumeId, question.id, compare.from, compare.to])


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
      {tab === 'write' ? (
        <div className="row">
          <h2 className="grow">{question.title}</h2>
          {/* 작성 탭은 '지금 편집 중인 버전' 표시만. 목록·삭제·비교는 버전 탭(10/29) */}
          {loaded && (
            <span className="ver-badge editing">
              v{loaded.no}{loaded.id === versions[0]?.id ? ' (최신)' : ''} 편집 중
            </span>
          )}
          {/* A6 리라이팅: 고른 후보를 이 문항의 새 버전으로 저장할 수 있게 자소서·문항 ID를 넘긴다(A 요청 10/28) */}
          <Link to={`/writing?${new URLSearchParams({ resume: resumeId, question: question.id })}`}>글 다듬기</Link>
          <button className="danger" onClick={onDelete}>
            문항 삭제
          </button>
        </div>
      ) : (
        <div className="row">
          <h2 className="grow">
            {question.title} <span className="muted ver-count">버전 {versions.length}/{MAX_VERSIONS}</span>
          </h2>
          <label className="muted share-toggle">
            <input type="checkbox" checked={showEnded} onChange={(e) => setShowEnded(e.target.checked)} /> 지난 공유 보기
          </label>
        </div>
      )}
      {tab === 'write' && (
        <>
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
        {/* 유형 먼저 → 그 유형의 경험 중에서 선택(10/28). 이미 연결한 경험은 제외 */}
        <select value={pickType} onChange={(e) => { setPickType(e.target.value); setPick('') }} aria-label="경험 유형">
          <option value="">유형 선택</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t} ({candidates.filter((e) => normalizeType(e.type) === t).length})
            </option>
          ))}
        </select>
        <select value={pick} onChange={(e) => setPick(e.target.value)} disabled={!pickType} aria-label="끌어올 경험">
          <option value="">{pickType ? '경험 선택' : '유형을 먼저 선택하세요'}</option>
          {candidates.filter((e) => normalizeType(e.type) === pickType).map((e) => (
            <option key={e.id} value={e.id}>
              {e.title}
            </option>
          ))}
        </select>
        <button className="secondary" onClick={pullExperience} disabled={!pick}>
          연결
        </button>
        <span className="muted">AI 참고용으로 문항에 연결합니다. 본문에는 넣지 않습니다.</span>
      </div>
      {linked.length > 0 && (
        <div className="card linked-card">
          <ul className="list linked-list">
            {linked.map((e) => (
              <li key={e.id}>
                {/* 행을 누르면 경험 열람. 연결 해제 버튼은 덮개 위라 따로 동작 */}
                <span className="linked-type">{normalizeType(e.type)}</span>
                <Link to={`/experiences/${e.id}`} className="linked-title">{e.title}</Link>
                <span className="muted">{period(e) || '기간 없음'}</span>
                <button className="secondary" onClick={() => unlinkExperience(e.id)}>
                  연결 해제
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

        </>
      )}

      {tab === 'versions' && (
        <>
          <VersionList versions={versions} selectedId={preview?.id} loadedId={loaded?.id}
            onSelect={selectPreview} onDelete={removeVersion} />
          {preview && (
            <div className="card ver-preview">
              <div className="row">
                <strong className="grow">v{preview.no} 미리보기</strong>
                <span className="muted">{preview.body.length.toLocaleString()}자</span>
                <button onClick={continueFrom} disabled={preview.id === loaded?.id && body === loaded.body}>
                  이 버전으로 작성 이어가기
                </button>
              </div>
              <div className="ver-preview-body">{preview.body || <span className="muted">(빈 본문)</span>}</div>
            </div>
          )}
          {notice && <p className="notice">{notice}</p>}
          {error && <p className="error">{error}</p>}
        </>
      )}

      {tab === 'versions' && versions.length >= 2 && (
        <>
          <h3>버전 비교</h3>
          {/* 고르면 바로 비교(10/28). 기본은 '지금 보는 버전'과 그 직전 버전 */}
          <div className="row">
            {['from', 'to'].map((k, i) => (
              <span key={k} className="diff2-pick">
                {i === 1 && <span aria-hidden="true">→</span>}
              <select value={compare[k]} onChange={(e) => setCompare({ ...compare, [k]: e.target.value })}
                aria-label={k === 'from' ? '이전 버전' : '이후 버전'}>
                <option value="">{k === 'from' ? '이전' : '이후'}</option>
                {versions.map((v) => (
                  <option key={v.id} value={v.version_no}>
                    v{v.version_no}
                  </option>
                ))}
              </select>
              </span>
            ))}
          </div>
          {diff && <DiffView diff={diff} />}
        </>
      )}
    </div>
  )
}
