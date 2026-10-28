import { useCallback, useEffect, useState } from 'react'
import { roadmapsApi } from './api.js'
import { ApiError } from '../../app/api/client.js'
import './learning.css'

// 공고가 요구하는 역량(갭). 필수=required, 우대=preferred, 참고=mentioned (백엔드 enum).
// 역량 키는 수집된 K-MOOC 강좌의 competency_keys 와 맞춘다(실제 매칭되는 것만 노출).
const SKILLS = [
  { key: 'aws', label: '클라우드(AWS)', importance: 'required', desc: 'K-MOOC 클라우드 과정' },
  { key: 'security', label: '정보보안', importance: 'required', desc: 'K-MOOC 보안 과정' },
  { key: 'python', label: 'Python', importance: 'preferred', desc: 'K-MOOC 파이썬 과정' },
]
const SUGGEST = [
  { key: 'network', label: '네트워크' },
]
const IMPORTANCE_LABEL = { required: '필수', preferred: '우대', mentioned: '참고' }
const MODE_LABEL = { online: '온라인', offline: '오프라인' }

export default function LearningPage() {
  const [weeklyHours, setWeeklyHours] = useState(5)
  const [mode, setMode] = useState(null) // null=전체, 'online'|'offline'
  const [gaps, setGaps] = useState([SKILLS[0], SKILLS[1]]) // 로드맵에 넣을 역량
  const [custom, setCustom] = useState('')

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

  const hasGap = (key) => gaps.some((g) => g.key === key)
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
          evidence_fields: [],
        })),
        weekly_hours: weeklyHours,
      }
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
      <div className="roadmap-heading">
        <div>
          <p className="eyebrow">NESUME · 학습 추천</p>
          <h1 className="page-heading">맞춤 학습 로드맵</h1>
          <p className="page-subtitle">부족 역량을 고르면 서버가 주차별 학습 계획을 만들어 줍니다.</p>
        </div>
        <div className="hours-control">
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

      <div className="roadmap-method-row">
        <strong>학습 방법</strong>
        {Object.entries(MODE_LABEL).map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={`method-chip ${mode === value ? 'method-chip-active' : ''}`}
            onClick={() => setMode((m) => (m === value ? null : value))}
          >
            {label}
          </button>
        ))}
        <span className="roadmap-muted">선택 안 하면 전체에서 추천</span>
      </div>

      <div className="roadmap-layout">
        <aside className="panel skill-panel">
          <div className="panel-heading">
            <div>
              <h3>학습 역량</h3>
              <p>로드맵에 넣을 역량을 고르세요. 공고가 요구하는 역량 예시입니다.</p>
            </div>
            <span className="tiny-label">갭 · 예시</span>
          </div>
          {SKILLS.map((skill) => (
            <div key={skill.key} className={`skill-card ${hasGap(skill.key) ? 'skill-card-added' : ''}`}>
              <div className="skill-card-copy">
                <span className={`skill-level ${skill.importance === 'required' ? 'skill-required' : 'skill-preferred'}`}>
                  {IMPORTANCE_LABEL[skill.importance]}
                </span>
                <strong>{skill.label}</strong>
                <p>{skill.desc}</p>
              </div>
              {hasGap(skill.key) ? (
                <span className="added-mark">✓ 추가됨</span>
              ) : (
                <button className="btn-primary skill-add" onClick={() => addGap(skill)}>추가</button>
              )}
            </div>
          ))}
          <div className="skill-suggest">
            <span className="suggest-tag">참고</span>
            <span>눌러서 로드맵에 추가</span>
            <div className="skill-tags">
              {SUGGEST.map((t) => (
                <button key={t.key} onClick={() => addGap({ ...t, importance: 'mentioned' })} className={hasGap(t.key) ? 'skill-tag selected' : 'skill-tag'}>
                  + {t.label}
                </button>
              ))}
            </div>
          </div>
          <form className="custom-skill-form" onSubmit={addCustom}>
            <input aria-label="직접 역량 추가" value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="직접 추가할 역량" />
            <button type="submit">추가</button>
          </form>

          {gaps.length > 0 && (
            <div className="selected-skills-line">
              <span>선택 역량</span>
              {gaps.map((g) => (
                <span className="selected-skill" key={g.key}>
                  {g.label}
                  <button aria-label={`${g.label} 제거`} onClick={() => removeGap(g.key)}>×</button>
                </span>
              ))}
            </div>
          )}

          <button className="btn-primary btn-full" onClick={generate} disabled={creating || gaps.length === 0}>
            {creating ? '생성 중…' : roadmap ? '로드맵 다시 생성' : '로드맵 생성'}
          </button>
        </aside>

        <section className="panel roadmap-list-panel">
          <div className="panel-heading">
            <div>
              <div className="inline-head">
                <h3>내 로드맵</h3>
                {roadmap && <span className="roadmap-edit-label">{roadmap.grade}</span>}
              </div>
              <p>필수 역량부터 앞 주차에 배치됩니다.</p>
            </div>
            {roadmap && (
              <div className="roadmap-progress">
                <strong>{doneCount}/{items.length}</strong>
                <span>완료</span>
              </div>
            )}
          </div>

          {loading && <div className="roadmap-empty"><strong>불러오는 중…</strong></div>}

          {!loading && error && (
            <div className="roadmap-empty roadmap-error">
              <strong>문제가 발생했습니다</strong>
              <p>{error}</p>
            </div>
          )}

          {!loading && !error && !roadmap && (
            <div className="roadmap-empty">
              <strong>아직 로드맵이 없어요</strong>
              <p>왼쪽에서 역량을 고르고 <strong>로드맵 생성</strong>을 눌러 주세요.</p>
            </div>
          )}

          {!loading && !error && roadmap && items.length === 0 && (
            <div className="roadmap-empty">
              <strong>항목이 없습니다</strong>
              <p>선택한 역량으로 만들 수 있는 학습이 없어요.</p>
            </div>
          )}

          {!loading && !error && roadmap && items.length > 0 && (
            <>
              <div className="roadmap-explain-row">
                <button className="btn-secondary" onClick={explain} disabled={explaining}>
                  {explaining ? '설명 생성 중…' : roadmap.explanation ? '설명 다시 생성' : '왜 이 순서인지 설명'}
                </button>
                {roadmap.explanation && <p className="roadmap-explanation">{roadmap.explanation}</p>}
              </div>

              {weeks.map((week) => (
                <div className="roadmap-week" key={week}>
                  <div className="week-title">{week}주차</div>
                  {items
                    .filter((i) => i.week === week)
                    .sort((a, b) => a.position - b.position)
                    .map((item) => (
                      <article key={item.id} className={`lesson-card ${item.status === 'done' ? 'lesson-complete' : ''}`}>
                        <label className="lesson-check">
                          <input type="checkbox" checked={item.status === 'done'} onChange={() => toggleItem(item)} />
                          <span className="sr-only">{item.title} 완료</span>
                        </label>
                        <div className="lesson-main">
                          <div className="lesson-title-row">
                            <h4>{item.title}</h4>
                            {item.source && <span className="lesson-mode mode-online">{item.source}</span>}
                          </div>
                          <p className="lesson-provider">
                            {item.provider ?? '제공처 미상'}
                            {item.hours != null && ` · ${item.hours}h`}
                            {item.certificate && ' · 수료증'}
                          </p>
                          {item.url && (
                            <div className="lesson-meta-row">
                              <a className="lesson-link" href={item.url} target="_blank" rel="noopener noreferrer">
                                강좌 열기 ↗ (외부 사이트)
                              </a>
                              {item.unverified && <span className="lesson-tag">미검증 링크</span>}
                            </div>
                          )}
                        </div>
                      </article>
                    ))}
                </div>
              ))}

              <div className="roadmap-note">
                <span>주차 배치·완료 상태는 서버에 저장됩니다. 외부 강좌 링크는 새 탭으로 열립니다.</span>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
