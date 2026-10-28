import { useCallback, useEffect, useState } from 'react'
import { roadmapsApi, learningGapsApi } from './api.js'
import { resumesApi } from '../resumes/api.js'
import { applicationsApi } from '../applications/api.js'
import { recommendApi } from '../recommend/api.js'
import { ApiError } from '../../app/api/client.js'
import '../c-common.css'
import './learning.css'

const IMPORTANCE_LABEL = { required: '필수', preferred: '우대', mentioned: '참고' }
const MODE_LABEL = { online: '온라인', offline: '오프라인' }

// 부족 역량 카드 — 넣기/빼기 토글(로드맵 생성 시 들어갈 역량)
function GapCard({ g, on, onToggle }) {
  return (
    <div className={`c-skill-card ${on ? 'c-skill-card-added' : ''}`}>
      <div className="c-skill-card-copy">
        <span className={`c-skill-level ${g.importance === 'required' ? 'c-skill-required' : 'c-skill-preferred'}`}>
          {IMPORTANCE_LABEL[g.importance] ?? g.importance}
        </span>
        <strong>{g.label}</strong>
      </div>
      <button className={`${on ? 'c-btn-secondary' : 'c-btn-primary'} c-skill-add`} onClick={() => onToggle(g)}>
        {on ? '빼기' : '넣기'}
      </button>
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
  const [gapInfo, setGapInfo] = useState(null) // /learning-gaps 응답(gaps·domain_gaps·conditions·covered·counts)
  const [showCovered, setShowCovered] = useState(false)
  const [gapsLoading, setGapsLoading] = useState(false)

  const [roadmap, setRoadmap] = useState(null) // 현재 로드맵(RoadmapOut) 또는 null
  const [loading, setLoading] = useState(true) // 최초 목록 조회
  const [creating, setCreating] = useState(false)
  const [explaining, setExplaining] = useState(false)
  const [error, setError] = useState(null)

  // 최초: 기존 로드맵이 있으면 가장 최근 것을 보여준다.
  const loadList = useCallback(async (signal) => {
    setLoading(true)
    try {
      const list = await roadmapsApi.list({ signal })
      if (signal?.aborted) return
      setRoadmap(list.length ? list[list.length - 1] : null)
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

  const pickPosting = async (pid) => {
    setPostingId(pid)
    setGaps([])
    setGapInfo(null)
    setGapsLoading(true)
    setError(null)
    try {
      const res = await learningGapsApi.forPosting(resumeId, pid)
      setGaps(res.gaps) // 기술 역량은 기본 포함, 직무 역량은 사용자가 고르면
      setGapInfo(res)
      setShowCovered(false)
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

  const generate = async () => {
    if (!gaps.length) return
    setCreating(true)
    setError(null)
    try {
      const payload = {
        gaps: gaps.map((g) => ({
          key: g.key,
          label: g.label,
          importance: g.importance,
          evidence_fields: g.evidence_fields ?? [],
        })),
        weekly_hours: weeklyHours,
      }
      if (postingId) payload.job_posting_id = postingId
      if (mode) payload.mode = mode
      const created = await roadmapsApi.create(payload)
      setRoadmap(created)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '로드맵 생성에 실패했습니다.')
    } finally {
      setCreating(false)
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

  const explain = async () => {
    if (!roadmap) return
    setExplaining(true)
    try {
      const updated = await roadmapsApi.explain(roadmap.id)
      setRoadmap(updated)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '설명 생성에 실패했습니다.')
    } finally {
      setExplaining(false)
    }
  }

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
            onClick={() => setMode((m) => (m === value ? null : value))}
          >
            {label}
          </button>
        ))}
        <span className="c-roadmap-muted">선택 안 하면 전체에서 추천</span>
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
                        <span className="lp-posting-title">{p.posting?.title ?? '(제목 없음)'}</span>
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
                <h4>③ 부족한 역량</h4>
                {gapInfo && gapInfo.covered.length > 0 && (
                  <button type="button" className="lp-link" onClick={() => setShowCovered((v) => !v)}>
                    이미 갖춤 {gapInfo.covered.length}개 {showCovered ? '▴' : '▾'}
                  </button>
                )}
              </div>
              {gapsLoading && <p className="c-roadmap-muted">자소서·경험과 공고를 비교하는 중…</p>}

              {gapInfo && showCovered && (
                <ul className="lp-covered">
                  {gapInfo.covered.map((c) => (
                    <li key={c.label}>
                      <strong>{c.label}</strong>
                      <span>
                        {c.status === 'covered'
                          ? '자소서에 있음'
                          : `경험에만 있음${c.experiences.length ? ` · ${c.experiences.join(', ')}` : ''}`}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {gapInfo && (
                <>
                  <p className="lp-group-title">기술 역량 <span>로드맵에 기본으로 넣어요</span></p>
                  {gapInfo.gaps.length === 0 && <p className="c-roadmap-muted">부족한 기술 역량이 없습니다.</p>}
                  {gapInfo.gaps.map((g) => <GapCard key={g.key} g={g} on={hasGap(g.key)} onToggle={toggleGap} />)}

                  {gapInfo.domain_gaps.length > 0 && (
                    <>
                      <p className="lp-group-title">
                        직무 역량 <span>필요하면 골라 넣어요 · 맞는 강좌가 적을 수 있어요</span>
                      </p>
                      {gapInfo.domain_gaps.map((g) => (
                        <GapCard key={g.key} g={g} on={hasGap(g.key)} onToggle={toggleGap} />
                      ))}
                    </>
                  )}

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

          <button className="c-btn-primary c-btn-full" onClick={generate} disabled={creating || gaps.length === 0}>
            {creating ? '생성 중…' : roadmap ? '로드맵 다시 생성' : '로드맵 생성'}
          </button>
        </aside>

        <section className="c-panel c-roadmap-list-panel">
          <div className="c-panel-heading">
            <div>
              <div className="inline-head">
                <h3>내 로드맵</h3>
                {roadmap && <span className="c-roadmap-edit-label">{roadmap.grade}</span>}
              </div>
              <p>필수 역량부터 앞 주차에 배치됩니다.</p>
            </div>
            {roadmap && (
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

          {!loading && !error && !roadmap && (
            <div className="c-roadmap-empty">
              <strong>아직 로드맵이 없어요</strong>
              <p>왼쪽에서 역량을 고르고 <strong>로드맵 생성</strong>을 눌러 주세요.</p>
            </div>
          )}

          {!loading && !error && roadmap && items.length === 0 && (
            <div className="c-roadmap-empty">
              <strong>항목이 없습니다</strong>
              <p>선택한 역량으로 만들 수 있는 학습이 없어요.</p>
            </div>
          )}

          {!loading && !error && roadmap && items.length > 0 && (
            <>
              <div className="roadmap-explain-row">
                <button className="c-btn-secondary" onClick={explain} disabled={explaining}>
                  {explaining ? '설명 생성 중…' : roadmap.explanation ? '설명 다시 생성' : '왜 이 순서인지 설명'}
                </button>
                {roadmap.explanation && <p className="roadmap-explanation">{roadmap.explanation}</p>}
              </div>

              {weeks.map((week) => (
                <div className="c-roadmap-week" key={week}>
                  <div className="c-week-title">{week}주차</div>
                  {items
                    .filter((i) => i.week === week)
                    .sort((a, b) => a.position - b.position)
                    .map((item) => (
                      <article key={item.id} className={`c-lesson-card ${item.status === 'done' ? 'c-lesson-complete' : ''}`}>
                        <label className="c-lesson-check">
                          <input type="checkbox" checked={item.status === 'done'} onChange={() => toggleItem(item)} />
                          <span className="c-sr-only">{item.title} 완료</span>
                        </label>
                        <div className="c-lesson-main">
                          <div className="c-lesson-title-row">
                            <h4>{item.title}</h4>
                            {item.source && <span className="c-lesson-mode c-mode-online">{item.source}</span>}
                          </div>
                          <p className="c-lesson-provider">
                            {item.provider ?? '제공처 미상'}
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
                        </div>
                      </article>
                    ))}
                </div>
              ))}

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
