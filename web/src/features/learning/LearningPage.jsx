import { useCallback, useEffect, useState } from 'react'
import { roadmapsApi, learningGapsApi } from './api.js'
import { resumesApi } from '../resumes/api.js'
import { applicationsApi } from '../applications/api.js'
import { recommendApi } from '../recommend/api.js'
import { ApiError } from '../../app/api/client.js'
import CandidatesDialog from './CandidatesDialog.jsx'
import SavedRoadmapsPopover from './SavedRoadmapsPopover.jsx'
import { safeUrl } from '../safeUrl.js'
import '../c-common.css'
import './learning.css'

const IMPORTANCE_LABEL = { required: '필수', preferred: '우대', mentioned: '참고' }
const MODE_LABEL = { online: '온라인', offline: '오프라인' }
const SOURCE_LABEL = { kmooc: 'K-MOOC', work24: '고용24' }
const MAX_SAVED = 10 // 사용자당 저장본 한도(서버 MAX_SAVED_ROADMAPS와 같게)

// 로드맵 항목에 저장된 역량(gap_key·gap_label)을 처음 나온 순서대로 — 중요도는 왼쪽 목록에 같은 역량이 있으면 그 값
function roadmapGaps(r, known) {
  const seen = new Map()
  for (const i of [...(r.items ?? [])].sort((a, b) => (a.week ?? 99) - (b.week ?? 99) || a.position - b.position)) {
    if (i.gap_key && !seen.has(i.gap_key)) {
      const k = known.find((g) => g.key === i.gap_key)
      seen.set(i.gap_key, {
        key: i.gap_key,
        label: i.gap_label ?? i.gap_key,
        importance: k?.importance ?? 'required',
        evidence_fields: k?.evidence_fields ?? [],
      })
    }
  }
  return [...seen.values()]
}

// "내 로드맵" 선택 상자 문구: 생성일 · 회사 · 공고 · 학습 방법 · 진행
function roadmapLabel(r) {
  const d = new Date(r.created_at)
  const when = `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  const items = r.items ?? []
  const done = items.filter((i) => i.status === 'done').length
  const posting = [r.company_name, r.posting_title].filter(Boolean).join(' ')
  return [when, posting || '공고 미지정', MODE_LABEL[r.mode] ?? '전체', `${done}/${items.length} 완료`].join(' · ')
}

// 맞는 강좌를 못 찾은 갭 항목(시스템 항목인데 강좌 출처가 없음) — 강좌처럼 보이지 않게 구분
const noCourse = (item) => item.origin === 'system' && !item.source

// 공고 필드 → 근거 표시 이름(A11 PostingFields). 원문 줄(evidence_line)은 C10이 따로 찾아 준다.
const FIELD_LABEL = {
  title: '공고 제목',
  job_name: '직무명',
  job_content: '직무 내용',
  certificates: '자격·우대', // 고용24 sptCertEtc엔 자격증과 전공·우대가 섞여 온다
  preferred: '우대사항',
  major: '전공',
  computer_skills: '컴퓨터 활용',
}

// ③ 역량 갭 표 — 매칭률 + 요구 역량·구분·근거. 부족 행의 체크 = 로드맵에 넣을 역량.
// 매칭률 = 보유 ÷ (보유 + 부족), 기술·직무 역량만(지원 조건 제외).
function GapTable({ info, isOn, onToggle }) {
  const missing = [...info.gaps, ...info.domain_gaps.map((g) => ({ ...g, domain: true }))]
  const total = info.covered.length + missing.length
  const rate = total ? Math.round((info.covered.length / total) * 100) : null
  let rank = 0
  return (
    <div className="lp-gap">
      {rate !== null && (
        <div className="lp-gap-rate">
          <div className="lp-gap-rate-row">
            <span>자소서 매칭률</span>
            <strong>{rate}%</strong>
          </div>
          <div className="lp-gap-bar" role="progressbar" aria-valuenow={rate} aria-valuemin={0} aria-valuemax={100} aria-label="자소서 매칭률">
            <span style={{ width: `${rate}%` }} />
          </div>
        </div>
      )}
      {total === 0 ? (
        <p className="c-roadmap-muted">공고에서 대조할 기술·직무 역량을 찾지 못했습니다.</p>
      ) : (
        <table className="lp-gap-table">
          <thead>
            <tr>
              <th scope="col"><span className="c-sr-only">로드맵에 넣기</span></th>
              <th scope="col">요구 역량</th>
              <th scope="col">구분</th>
              <th scope="col">근거</th>
            </tr>
          </thead>
          <tbody>
            {info.covered.map((c) => (
              <tr key={`c-${c.label}`}>
                <td />
                <td>{c.label}</td>
                <td><span className="lp-gap-st have">보유</span></td>
                <td className="lp-gap-why">
                  {c.status === 'covered' ? '자소서' : `경험: ${c.experiences.join(', ') || '이름 없음'}`}
                </td>
              </tr>
            ))}
            {missing.map((g) => {
              const required = g.importance === 'required'
              if (required) rank += 1
              const fields = g.evidence_fields.map((f) => FIELD_LABEL[f] ?? f)
              return (
                <tr key={`m-${g.key}`}>
                  <td>
                    <input type="checkbox" checked={isOn(g.key)} onChange={() => onToggle(g)} aria-label={`${g.label} 로드맵에 넣기`} />
                  </td>
                  <td>
                    {g.label}{' '}
                    <span className={`lp-gap-imp ${required ? 'req' : ''}`}>{IMPORTANCE_LABEL[g.importance] ?? g.importance}</span>
                    {g.domain && <span className="lp-gap-imp">직무</span>}
                  </td>
                  <td>
                    <span className={`lp-gap-st ${required ? 'need' : 'nice'}`}>{required ? `부족 · ${rank}순위` : '부족'}</span>
                  </td>
                  <td className="lp-gap-why">
                    {fields.length ? `공고 ${fields.join(', ')}` : '공고'}
                    {g.evidence_line && (
                      <span className="lp-gap-line" title={g.evidence_line}>
                        「{g.evidence_line}」
                      </span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function LearningPage() {
  const [weeklyHours, setWeeklyHours] = useState(5)
  const [mode, setMode] = useState(null) // null=전체, 'online'|'offline'
  const [gaps, setGaps] = useState([]) // 로드맵에 넣을 역량(공고 대비 부족한 것)
  const [custom, setCustom] = useState('')

  // 맞춤 학습: ① 자소서 → ② 그 자소서 기준 추천 공고 → ③ 공고 대비 부족 역량(C10 /learning-gaps)
  const [resumes, setResumes] = useState(null) // null = 불러오는 중
  const [resumeId, setResumeId] = useState('')
  const [postings, setPostings] = useState(null) // 추천 공고(RecommendationOut[])
  const [postingsLoading, setPostingsLoading] = useState(false)
  const [appliedIds, setAppliedIds] = useState(() => new Set()) // 지원 현황에 있는 공고
  const [filter, setFilter] = useState('all') // all | applied | not
  const [postingId, setPostingId] = useState(null)
  const [fieldIdx, setFieldIdx] = useState(null) // 모집분야 순번(여럿인 공고만). null = 공고 전체
  const [gapInfo, setGapInfo] = useState(null) // /learning-gaps 응답(gaps·domain_gaps·conditions·covered·counts)
  const [gapsLoading, setGapsLoading] = useState(false)

  const [roadmap, setRoadmap] = useState(null) // 현재 로드맵(RoadmapOut) 또는 null
  const [roadmaps, setRoadmaps] = useState([]) // 저장본 전부 + 초안(사용자당 최대 1개), 최신순
  const [naming, setNaming] = useState(null) // [저장] 이름 입력 중이면 문자열
  const [loading, setLoading] = useState(true) // 최초 목록 조회
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState(null)

  // 최초: 기존 로드맵이 있으면 가장 최근 것을 보여준다.
  const loadList = useCallback(async (signal) => {
    setLoading(true)
    try {
      const list = await roadmapsApi.list({ signal })
      if (signal?.aborted) return
      setRoadmaps(list)
      // 하던 초안이 있으면 그것, 없으면 가장 최근 저장본(서버가 최근 수정순으로 준다)
      setRoadmap(list.find((r) => !r.saved_at) ?? list[0] ?? null)
      setError(null)
    } catch (e) {
      if (e.name === 'AbortError') return
      setError(e instanceof ApiError ? e.message : '로드맵을 불러오지 못했습니다.')
      setRoadmap(null)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const ctrl = new AbortController()
    loadList(ctrl.signal)
    return () => ctrl.abort()
  }, [loadList])

  // 자소서 목록 + 지원 현황(지원 여부 구분용)
  useEffect(() => {
    let alive = true
    Promise.all([resumesApi.list(), applicationsApi.list()])
      .then(([rs, apps]) => {
        if (!alive) return
        setResumes(rs)
        setAppliedIds(new Set(apps.map((a) => a.job_posting_id).filter(Boolean)))
      })
      .catch((e) => alive && setError(e instanceof ApiError ? e.message : '자소서를 불러오지 못했습니다.'))
    return () => {
      alive = false
    }
  }, [])

  const pickResume = async (rid) => {
    setResumeId(rid)
    setPostings(null)
    setPostingId(null)
    setGaps([])
    setGapInfo(null)
    if (!rid) return
    setPostingsLoading(true)
    setError(null)
    try {
      const res = await recommendApi.recommend({ resume_id: rid, top_k: 10 })
      setPostings(res.items)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '추천 공고를 불러오지 못했습니다.')
    } finally {
      setPostingsLoading(false)
    }
  }

  // 공고 선택 → 역량 갭. 모집분야가 여럿이면 추천이 찾은 "자소서에 맞는 분야"로 분석(바꿔 볼 수 있음)
  const pickPosting = async (pid, idx = postings?.find((p) => p.posting_id === pid)?.field_index ?? null) => {
    setPostingId(pid)
    setFieldIdx(idx)
    setGaps([])
    setGapInfo(null)
    setGapsLoading(true)
    setError(null)
    try {
      const res = await learningGapsApi.forPosting(resumeId, pid, idx)
      setGaps(res.gaps) // 기술 역량은 기본 포함, 직무 역량은 사용자가 고르면
      setGapInfo(res)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '부족 역량을 분석하지 못했습니다.')
    } finally {
      setGapsLoading(false)
    }
  }

  const shown = (postings ?? []).filter((p) => {
    const applied = appliedIds.has(p.posting_id)
    return filter === 'all' || (filter === 'applied' ? applied : !applied)
  })

  const hasGap = (key) => gaps.some((g) => g.key === key)
  const toggleGap = (g) => setGaps((v) => (v.some((x) => x.key === g.key) ? v.filter((x) => x.key !== g.key) : [...v, g]))
  const addGap = (g) => setGaps((v) => (v.some((x) => x.key === g.key) ? v : [...v, g]))
  const removeGap = (key) => setGaps((v) => v.filter((x) => x.key !== key))
  const addCustom = (e) => {
    e.preventDefault()
    const label = custom.trim()
    if (!label) return
    const key = label.toLowerCase()
    addGap({ key, label, importance: 'mentioned' })
    setCustom('')
  }

  // 새 로드맵을 만들어 목록 맨 위에 넣고 연다(이전 로드맵은 목록에 남는다)
  const generate = async ({ modeValue = mode, gapsValue = gaps, postingValue = postingId } = {}) => {
    if (!gapsValue.length) return
    setCreating(true)
    setError(null)
    try {
      const payload = {
        gaps: gapsValue.map((g) => ({
          key: g.key,
          label: g.label,
          importance: g.importance,
          evidence_fields: g.evidence_fields ?? [],
        })),
        weekly_hours: weeklyHours,
      }
      if (postingValue) payload.job_posting_id = postingValue
      if (modeValue) payload.mode = modeValue
      const created = await roadmapsApi.create(payload)
      setRoadmap(created)
      // 서버가 이전 초안을 지웠다(초안은 1개) — 목록에서도 저장본만 남기고 새 초안을 앞에
      setRoadmaps((list) => [created, ...list.filter((r) => r.saved_at)])
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '로드맵 생성에 실패했습니다.')
    } finally {
      setCreating(false)
    }
  }

  // 학습 방법을 바꾸면 **지금 보고 있는 로드맵의 역량·공고 그대로** 바로 새로 만든다(이전 것은 목록에 남음).
  // 역량 정보(gap_key)가 없는 예전 로드맵이면 왼쪽 "로드맵에 넣을 역량"을 쓴다.
  const changeMode = (next) => {
    if (creating) return
    setMode(next)
    if (!roadmap) return
    const fromRoadmap = roadmapGaps(roadmap, gaps)
    if (fromRoadmap.length) {
      generate({ modeValue: next, gapsValue: fromRoadmap, postingValue: roadmap.job_posting_id })
    } else if (gaps.length) {
      generate({ modeValue: next })
    }
  }

  // 저장된 로드맵 열기 / 삭제(되돌릴 수 없어 확인). 보고 있던 것을 지우면 초안 → 최근 저장본 순으로 연다.
  const savedRoadmaps = roadmaps.filter((r) => r.saved_at)
  const openRoadmap = (id) => setRoadmap(roadmaps.find((r) => r.id === id) ?? null)
  const deleteRoadmap = async (target) => {
    if (!target || !window.confirm(`'${target.name || roadmapLabel(target)}' 로드맵을 삭제할까요? 완료 체크·추가한 항목도 함께 지워집니다.`)) return
    try {
      await roadmapsApi.remove(target.id)
      const rest = roadmaps.filter((r) => r.id !== target.id)
      setRoadmaps(rest)
      if (roadmap?.id === target.id) setRoadmap(rest.find((r) => !r.saved_at) ?? rest[0] ?? null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '로드맵을 삭제하지 못했습니다.')
    }
  }

  // 초안 → 저장본(이름은 선택, 비우면 목록에 "회사 공고"로 보인다).
  // 저장본이 이미 MAX_SAVED개면 가장 오래 저장한 것이 지워진다고 알리고 확인을 받는다(서버도 확인 없으면 409).
  const saveRoadmap = async () => {
    if (!roadmap) return
    let oldest = null
    if (savedRoadmaps.length >= MAX_SAVED) {
      oldest = savedRoadmaps.reduce((a, b) => (a.saved_at <= b.saved_at ? a : b))
      const label = oldest.name || roadmapLabel(oldest)
      if (!window.confirm(`로드맵은 최대 ${MAX_SAVED}개까지 저장됩니다. 지금 저장하면 가장 오래된 로드맵 '${label}'이(가) 삭제됩니다. 저장하시겠습니까?`)) return
    }
    try {
      const saved = await roadmapsApi.save(roadmap.id, (naming ?? '').trim(), { replaceOldest: !!oldest })
      if (oldest) setRoadmaps((list) => list.filter((r) => r.id !== oldest.id))
      setRoadmap(saved)
      setNaming(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '로드맵을 저장하지 못했습니다.')
    }
  }

  const toggleItem = async (item) => {
    if (!roadmap) return
    const next = item.status === 'done' ? 'planned' : 'done'
    // 낙관적 반영
    setRoadmap((r) => ({
      ...r,
      items: r.items.map((x) => (x.id === item.id ? { ...x, status: next } : x)),
    }))
    try {
      await roadmapsApi.updateItem(roadmap.id, item.id, { status: next })
    } catch {
      // 실패 시 되돌림
      setRoadmap((r) => ({
        ...r,
        items: r.items.map((x) => (x.id === item.id ? { ...x, status: item.status } : x)),
      }))
      setError('완료 상태를 저장하지 못했습니다.')
    }
  }

  // 항목 삭제(되돌릴 수 없어 확인을 받는다)
  const removeItem = async (item) => {
    if (!roadmap || !window.confirm(`'${item.title}' 항목을 삭제할까요?`)) return
    try {
      await roadmapsApi.removeItem(roadmap.id, item.id)
      setRoadmap((r) => ({ ...r, items: r.items.filter((x) => x.id !== item.id) }))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '항목을 삭제하지 못했습니다.')
    }
  }

  // "맞는 강좌 없음" 갭 → 사용자가 찾은 강좌로 대체(같은 주차·순서에 추가 후 갭 항목 삭제)
  const [addFor, setAddFor] = useState(null) // 입력란을 연 갭 항목 id
  const [draft, setDraft] = useState({ title: '', url: '', hours: '' })
  const openAdd = (item) => {
    setAddFor(item.id)
    setDraft({ title: '', url: '', hours: '' })
  }
  const replaceWithUserItem = async (gap) => {
    const title = draft.title.trim()
    if (!roadmap || !title) return
    const url = draft.url.trim()
    if (url && !/^https?:\/\//i.test(url)) {
      setError('링크는 http:// 또는 https:// 로 시작해야 합니다.')
      return
    }
    try {
      const added = await roadmapsApi.addItem(roadmap.id, {
        title,
        url: url || null,
        hours: draft.hours === '' ? null : Number(draft.hours),
        week: gap.week,
      })
      const placed = await roadmapsApi.updateItem(roadmap.id, added.id, { position: gap.position })
      await roadmapsApi.removeItem(roadmap.id, gap.id)
      setRoadmap((r) => ({ ...r, items: [...r.items.filter((x) => x.id !== gap.id), placed] }))
      setAddFor(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '강좌를 추가하지 못했습니다.')
      loadList() // 일부만 반영됐을 수 있어 서버 상태로 다시 맞춘다
    }
  }

  // "이 역량 강좌 전체 보기" — 연 항목. 교체면 그 항목을, 추가면 새 항목을 반영한다.
  const [browseFor, setBrowseFor] = useState(null)
  const onPicked = (saved, replace) => {
    setRoadmap((r) => ({
      ...r,
      items: replace ? r.items.map((x) => (x.id === browseFor.id ? saved : x)) : [...r.items, saved],
    }))
    if (replace) setBrowseFor(saved)
  }

  useEffect(() => {
    if (roadmap) setRoadmaps((list) => list.map((r) => (r.id === roadmap.id ? roadmap : r)))
  }, [roadmap])

  const items = roadmap?.items ?? []
  const doneCount = items.filter((i) => i.status === 'done').length
  const weeks = [...new Set(items.map((i) => i.week).filter(Boolean))].sort((a, b) => a - b)

  return (
    <div className="learning-page">
      <div className="c-roadmap-heading">
        <div>
          <p className="c-eyebrow">NESUME · 학습 추천</p>
          <h1 className="c-page-heading">맞춤 학습 로드맵</h1>
          <p className="c-page-subtitle">자소서를 고르면 맞는 공고와 부족한 역량을 찾아 주차별 학습 계획을 만들어 줍니다.</p>
        </div>
        <div className="c-hours-control">
          <label htmlFor="weekly-hours">주당 학습 시간</label>
          <input
            id="weekly-hours"
            type="number"
            min="1"
            max="40"
            value={weeklyHours}
            onChange={(e) => setWeeklyHours(Math.max(1, Math.min(40, Number(e.target.value) || 1)))}
          />
          <span>시간</span>
        </div>
      </div>

      <div className="c-roadmap-method-row">
        <strong>학습 방법</strong>
        {Object.entries(MODE_LABEL).map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={`c-method-chip ${mode === value ? 'c-method-chip-active' : ''}`}
            onClick={() => changeMode(mode === value ? null : value)}
          >
            {label}
          </button>
        ))}
        <span className="c-roadmap-muted">선택 안 하면 전체에서 추천</span>
        {resumeId && (
          <SavedRoadmapsPopover
            roadmaps={savedRoadmaps}
            currentId={roadmap?.id}
            onOpen={openRoadmap}
            onDelete={deleteRoadmap}
          />
        )}
      </div>

      <div className="c-roadmap-layout">
        <aside className="c-panel skill-panel">
          <div className="c-panel-heading">
            <div>
              <h3>① 자소서 선택</h3>
              <p>자소서와 내 경험을 기준으로 공고를 추천하고, 공고 대비 부족한 역량을 찾습니다.</p>
            </div>
          </div>
          <select
            className="lp-select"
            aria-label="자소서 선택"
            value={resumeId}
            onChange={(e) => pickResume(e.target.value)}
            disabled={resumes === null}
          >
            <option value="">{resumes === null ? '불러오는 중…' : resumes.length ? '자소서를 고르세요' : '자소서가 없습니다'}</option>
            {(resumes ?? []).map((r) => (
              <option key={r.id} value={r.id}>{r.title}</option>
            ))}
          </select>

          {resumeId && (
            <>
              <div className="lp-step-head">
                <h4>② 추천 공고</h4>
                <div className="lp-filter" role="group" aria-label="지원 여부">
                  {[['all', '전체'], ['not', '미지원'], ['applied', '지원함']].map(([v, l]) => (
                    <button key={v} type="button" className={filter === v ? 'on' : ''} onClick={() => setFilter(v)}>{l}</button>
                  ))}
                </div>
              </div>
              {postingsLoading && <p className="c-roadmap-muted">추천 중…</p>}
              {postings && shown.length === 0 && <p className="c-roadmap-muted">해당하는 공고가 없습니다.</p>}
              <ul className="lp-postings">
                {shown.map((p) => {
                  const applied = appliedIds.has(p.posting_id)
                  return (
                    <li key={p.posting_id}>
                      <button
                        type="button"
                        className={`lp-posting ${postingId === p.posting_id ? 'on' : ''}`}
                        onClick={() => pickPosting(p.posting_id)}
                      >
                        <span className="lp-posting-title">
                          {p.posting?.company_name && <b>{p.posting.company_name}</b>} {p.posting?.title ?? '(제목 없음)'}
                          {p.field_index != null && p.posting?.field_names?.[p.field_index] && (
                            <span className="lp-posting-field">맞는 분야: {p.posting.field_names[p.field_index]}</span>
                          )}
                        </span>
                        <span className={`lp-badge ${applied ? 'applied' : ''}`}>{applied ? '지원함' : '미지원'}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </>
          )}

          {postingId && (
            <>
              <div className="lp-step-head">
                <h4>③ 역량 갭</h4>
                {(() => {
                  // 선택한 공고의 원문(기업 채용 페이지) — 새 창, 서버는 가져오지 않음
                  const href = safeUrl(postings?.find((p) => p.posting_id === postingId)?.posting?.url)
                  return href ? (
                    <a className="lp-link" href={href} target="_blank" rel="noopener noreferrer" title="외부 사이트(기업 채용 페이지)로 이동">
                      원문 보기 ↗
                    </a>
                  ) : (
                    <span className="c-roadmap-muted">원문 링크 없음</span>
                  )
                })()}
              </div>
              {(() => {
                // 모집분야가 여럿인 공고: 자소서에 맞는 분야로 분석(기본), 다른 분야로 바꿔 보기
                const names = postings?.find((p) => p.posting_id === postingId)?.posting?.field_names ?? []
                if (names.length < 2) return null
                return (
                  <label className="lp-field-pick">
                    모집분야
                    <select
                      value={fieldIdx ?? ''}
                      onChange={(e) => pickPosting(postingId, e.target.value === '' ? null : Number(e.target.value))}
                    >
                      <option value="">공고 전체</option>
                      {names.map((n, i) => (
                        <option key={i} value={i}>{n}</option>
                      ))}
                    </select>
                  </label>
                )
              })()}
              {gapsLoading && <p className="c-roadmap-muted">자소서·경험과 공고를 비교하는 중…</p>}

              {gapInfo && (
                <>
                  <p className="lp-group-title">체크한 부족 역량이 로드맵에 들어가요 <span>직무 역량은 맞는 강좌가 적을 수 있어요</span></p>
                  <GapTable info={gapInfo} isOn={hasGap} onToggle={toggleGap} />

                  {gapInfo.conditions.length > 0 && (
                    <div className="lp-conditions">
                      <p className="lp-group-title">지원 조건 <span>배울 대상이 아니라 참고용이에요</span></p>
                      {gapInfo.conditions.map((c) => (
                        <span className="lp-cond" key={c.label}>
                          <b>{c.kind}</b> {c.label}
                        </span>
                      ))}
                    </div>
                  )}
                </>
              )}

              <form className="c-custom-skill-form" onSubmit={addCustom}>
                <input aria-label="직접 역량 추가" value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="직접 추가할 역량" />
                <button type="submit">추가</button>
              </form>
            </>
          )}

          {gaps.length > 0 && (
            <div className="c-selected-skills-line">
              <span>로드맵에 넣을 역량</span>
              {gaps.map((g) => (
                <span className="c-selected-skill" key={g.key}>
                  {g.label}
                  <button aria-label={`${g.label} 빼기`} onClick={() => removeGap(g.key)}>×</button>
                </span>
              ))}
            </div>
          )}

          <button className="c-btn-primary c-btn-full" onClick={() => generate()} disabled={creating || gaps.length === 0}>
            {creating ? '생성 중…' : roadmap ? '로드맵 다시 생성' : '로드맵 생성'}
          </button>
        </aside>

        <section className="c-panel c-roadmap-list-panel">
          <div className="c-panel-heading">
            <div>
              <div className="inline-head">
                <h3>내 로드맵</h3>
              </div>
              {resumeId && roadmap && (
                <div className="lp-roadmap-picker">
                  {roadmap.saved_at ? (
                    <span className="lp-saved-tag">저장됨 · {roadmap.name || roadmapLabel(roadmap)}</span>
                  ) : naming === null ? (
                    <>
                      <span className="lp-draft-tag">초안 · 저장 안 됨 (새로 만들면 사라집니다)</span>
                      <button type="button" className="c-btn-primary lp-save-btn" onClick={() => setNaming('')}>
                        저장
                      </button>
                    </>
                  ) : (
                    <form
                      className="lp-save-form"
                      onSubmit={(e) => {
                        e.preventDefault()
                        saveRoadmap()
                      }}
                    >
                      <input
                        autoFocus
                        maxLength={200}
                        placeholder="이름 (선택) 예: 삼성 보안 준비"
                        value={naming}
                        onChange={(e) => setNaming(e.target.value)}
                      />
                      <button type="submit" className="c-btn-primary">저장</button>
                      <button type="button" className="c-btn-secondary" onClick={() => setNaming(null)}>
                        취소
                      </button>
                    </form>
                  )}
                  <button type="button" className="c-btn-secondary lp-save-btn lp-danger-btn" onClick={() => deleteRoadmap(roadmap)}>
                    삭제
                  </button>
                </div>
              )}
              <p>필수 역량부터 앞 주차에 배치됩니다.</p>
            </div>
            {resumeId && roadmap && (
              <div className="c-roadmap-progress">
                <strong>{doneCount}/{items.length}</strong>
                <span>완료</span>
              </div>
            )}
          </div>

          {loading && <div className="c-roadmap-empty"><strong>불러오는 중…</strong></div>}

          {!loading && error && (
            <div className="c-roadmap-empty roadmap-error">
              <strong>문제가 발생했습니다</strong>
              <p>{error}</p>
            </div>
          )}

          {!loading && !error && !resumeId && (
            <div className="c-roadmap-empty">
              <strong>자소서를 고르세요</strong>
              <p>왼쪽에서 자소서를 고르면 로드맵이 보입니다.</p>
            </div>
          )}

          {!loading && !error && resumeId && !roadmap && (
            <div className="c-roadmap-empty">
              <strong>아직 로드맵이 없어요</strong>
              <p>왼쪽에서 역량을 고르고 <strong>로드맵 생성</strong>을 눌러 주세요.</p>
            </div>
          )}

          {!loading && !error && resumeId && roadmap && items.length === 0 && (
            <div className="c-roadmap-empty">
              <strong>항목이 없습니다</strong>
              <p>선택한 역량으로 만들 수 있는 학습이 없어요.</p>
            </div>
          )}

          {!loading && !error && resumeId && roadmap && items.length > 0 && (
            <>
              {weeks.map((week) => (
                <div className="c-roadmap-week" key={week}>
                  <div className="c-week-title">{week}주차</div>
                  {items
                    .filter((i) => i.week === week)
                    .sort((a, b) => a.position - b.position)
                    .map((item) => (
                      <article
                        key={item.id}
                        className={`c-lesson-card ${item.status === 'done' ? 'c-lesson-complete' : ''} ${noCourse(item) ? 'c-lesson-nocourse' : ''}`}
                      >
                        <label className="c-lesson-check">
                          <input type="checkbox" checked={item.status === 'done'} onChange={() => toggleItem(item)} />
                          <span className="c-sr-only">{item.title} 완료</span>
                        </label>
                        <div className="c-lesson-main">
                          <div className="c-lesson-title-row">
                            <h4>{item.title}</h4>
                            {item.mode && (
                              <span className={`c-lesson-mode c-mode-${item.mode}`}>{MODE_LABEL[item.mode] ?? item.mode}</span>
                            )}
                            {item.match_kind === 'semantic' && (
                              <span className="lp-ai-badge">AI 추천 · 관련도 낮을 수 있음</span>
                            )}
                          </div>
                          <p className="c-lesson-provider">
                            {noCourse(item)
                              ? '맞는 강좌 없음 — 직접 찾아 추가'
                              : item.origin === 'user'
                                ? '직접 추가'
                                : [SOURCE_LABEL[item.source] ?? item.source, item.provider].filter(Boolean).join(' · ')}
                            {item.hours != null && ` · ${item.hours}h`}
                            {item.certificate && ' · 수료증'}
                          </p>
                          {item.url && (
                            <div className="c-lesson-meta-row">
                              <a className="c-lesson-link" href={item.url} target="_blank" rel="noopener noreferrer">
                                강좌 열기 ↗ (외부 사이트)
                              </a>
                              {item.unverified && <span className="c-lesson-tag">미검증 링크</span>}
                            </div>
                          )}
                          {item.gap_key && (
                            <button type="button" className="lp-browse-btn" onClick={() => setBrowseFor(item)}>
                              이 역량 강좌 전체 보기
                            </button>
                          )}
                          {noCourse(item) && addFor !== item.id && (
                            <button type="button" className="c-btn-secondary lp-add-btn" onClick={() => openAdd(item)}>
                              + 강좌 추가
                            </button>
                          )}
                          {noCourse(item) && addFor === item.id && (
                            <form
                              className="lp-add-form"
                              onSubmit={(e) => {
                                e.preventDefault()
                                replaceWithUserItem(item)
                              }}
                            >
                              <input
                                required
                                maxLength={200}
                                placeholder="강좌 이름 (필수)"
                                value={draft.title}
                                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                              />
                              <input
                                type="url"
                                placeholder="링크 https://… (선택)"
                                value={draft.url}
                                onChange={(e) => setDraft({ ...draft, url: e.target.value })}
                              />
                              <input
                                type="number"
                                min="0"
                                max="1000"
                                step="0.5"
                                placeholder="시간(h, 선택)"
                                value={draft.hours}
                                onChange={(e) => setDraft({ ...draft, hours: e.target.value })}
                              />
                              <div className="lp-add-actions">
                                <button type="submit" className="c-btn-primary">추가</button>
                                <button type="button" className="c-btn-secondary" onClick={() => setAddFor(null)}>
                                  취소
                                </button>
                              </div>
                            </form>
                          )}
                        </div>
                        <button
                          type="button"
                          className="lp-item-remove"
                          aria-label={`${item.title} 삭제`}
                          title="삭제"
                          onClick={() => removeItem(item)}
                        >
                          ×
                        </button>
                      </article>
                    ))}
                </div>
              ))}

              {browseFor && (
                <CandidatesDialog
                  key={browseFor.id}
                  roadmapId={roadmap.id}
                  item={browseFor}
                  onClose={() => setBrowseFor(null)}
                  onPicked={onPicked}
                />
              )}

              <div className="c-roadmap-note">
                <span>주차 배치·완료 상태는 서버에 저장됩니다. 외부 강좌 링크는 새 탭으로 열립니다.</span>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
