import { useState } from 'react'
import { recommendApi } from './api.js'
import { applicationsApi } from '../applications/api.js'
import { ApiError } from '../../app/api/client.js'
import './recommend.css'

// 역량 갭 막대는 추천 응답에 없는 데이터(C10 영역)라 "데모"로 라벨만 남긴다.
const GAP_DEMO = [
  { label: '네트워크 기초', value: 82 },
  { label: 'Linux 운영', value: 70 },
  { label: '클라우드 보안', value: 45 },
  { label: '로그 분석', value: 60 },
]

const pct = (v) => `${Math.round((v ?? 0) * 100)}%`

// 요건 중요도 라벨(A11 importance)
const IMPORTANCE = [
  ['required', '필수'],
  ['preferred', '우대'],
  ['mentioned', '언급'],
]

export default function RecommendPage() {
  const [heldText, setHeldText] = useState('aws, docker, iam')
  const [result, setResult] = useState(null) // null=아직 실행 안 함
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [appliedIds, setAppliedIds] = useState(() => new Set())
  const [applyingId, setApplyingId] = useState(null)
  const [details, setDetails] = useState({}) // posting_id -> { open, loading, matches, error }

  const toggleDetail = async (id) => {
    const cur = details[id]
    if (cur?.open) {
      setDetails((d) => ({ ...d, [id]: { ...cur, open: false } }))
      return
    }
    if (cur?.matches) {
      setDetails((d) => ({ ...d, [id]: { ...cur, open: true } }))
      return
    }
    setDetails((d) => ({ ...d, [id]: { open: true, loading: true } }))
    try {
      const data = await recommendApi.postingDetail(id)
      setDetails((d) => ({ ...d, [id]: { open: true, loading: false, matches: data.matches } }))
    } catch (err) {
      setDetails((d) => ({
        ...d,
        [id]: { open: true, loading: false, error: err instanceof ApiError ? err.message : '상세를 불러오지 못했습니다.' },
      }))
    }
  }

  const applyTo = async (it) => {
    setApplyingId(it.posting_id)
    setError(null)
    try {
      await applicationsApi.create({
        status: 'applied',
        job_posting_id: it.posting_id,
        memo: it.posting?.title ?? null,
      })
      setAppliedIds((s) => new Set(s).add(it.posting_id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '지원 등록에 실패했습니다.')
    } finally {
      setApplyingId(null)
    }
  }

  const run = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const held_keys = heldText
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      const data = await recommendApi.recommend({
        held_keys,
        region_codes: [],
        job_codes: [],
        top_k: 20,
      })
      setResult(data)
    } catch (err) {
      if (err.name === 'AbortError') return
      setError(err instanceof ApiError ? err.message : '추천을 불러오지 못했습니다.')
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rec-page">
      <div>
        <p className="eyebrow">CAREER MATCH</p>
        <h1 className="page-heading">공고 추천 · 역량 분석</h1>
        <p className="page-subtitle">보유 역량을 넣으면 맞춤 공고를 추천합니다. (추천 결과는 데모 데이터입니다)</p>
      </div>

      <form className="panel" onSubmit={run}>
        <div className="rec-form-grid">
          <div className="rec-form-wide">
            <label className="field-label" htmlFor="rec-held">보유 역량 (쉼표로 구분)</label>
            <input
              id="rec-held"
              className="field"
              value={heldText}
              onChange={(e) => setHeldText(e.target.value)}
              placeholder="예: aws, docker, iam, linux"
            />
          </div>
          <button className="btn-primary btn-full" type="submit" disabled={loading}>
            {loading ? '분석 중…' : '맞춤 분석 실행'}
          </button>
        </div>
      </form>

      {/* 1) 추천 공고 목록 — 실제 /recommendations 응답 */}
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h3>추천 공고</h3>
            <p>POST /recommendations · 점수 = 0.5 벡터 + 0.5 키워드율</p>
          </div>
          {result && !result.cold_start && (
            <span className="tiny-label">{result.items.length}건</span>
          )}
        </div>

        {loading && <div className="rec-state">불러오는 중…</div>}

        {!loading && error && (
          <div className="rec-state rec-state-error">
            <strong>추천을 불러오지 못했습니다</strong>
            <p>{error}</p>
          </div>
        )}

        {!loading && !error && result === null && (
          <div className="rec-state">보유 역량을 넣고 <strong>맞춤 분석 실행</strong>을 눌러 주세요.</div>
        )}

        {!loading && !error && result?.cold_start && (
          <div className="rec-state">
            <strong>아직 추천할 공고가 없어요</strong>
            <p>{result.notice}</p>
          </div>
        )}

        {!loading && !error && result && !result.cold_start && result.items.length === 0 && (
          <div className="rec-state">조건에 맞는 공고가 없습니다.</div>
        )}

        {!loading && !error && result && !result.cold_start && result.items.length > 0 && (
          <ul className="rec-list">
            {result.items.map((it) => (
              <li key={it.posting_id} className="rec-item">
                <div className="rec-item-head">
                  <strong className="rec-item-title">{it.posting?.title ?? '(제목 비공개)'}</strong>
                  <span className="rec-item-score">{pct(it.score)}</span>
                </div>
                <p className="rec-item-job">{it.posting?.job_name ?? '직무 미상'}</p>
                <div className="rec-item-meta">
                  <span className="rec-chip rec-chip-vec">벡터 {pct(it.vector_score)}</span>
                  <span className="rec-chip rec-chip-kw">키워드 {pct(it.keyword_score)}</span>
                </div>
                {it.matched_keywords.length > 0 && (
                  <div className="rec-matched">
                    <span className="rec-matched-label">매칭 역량</span>
                    {it.matched_keywords.map((k) => (
                      <span className="rec-tag" key={k}>{k}</span>
                    ))}
                  </div>
                )}
                <div className="rec-item-actions">
                  <button className="btn-secondary rec-detail-btn" onClick={() => toggleDetail(it.posting_id)}>
                    {details[it.posting_id]?.open ? '상세 접기 ▴' : '상세 보기 ▾'}
                  </button>
                  {appliedIds.has(it.posting_id) ? (
                    <span className="rec-applied">✓ 지원 현황에 추가됨</span>
                  ) : (
                    <button
                      className="btn-primary rec-apply-btn"
                      onClick={() => applyTo(it)}
                      disabled={applyingId === it.posting_id}
                    >
                      {applyingId === it.posting_id ? '등록 중…' : '이 공고에 지원'}
                    </button>
                  )}
                </div>

                {details[it.posting_id]?.open && (
                  <div className="rec-detail">
                    {details[it.posting_id].loading && <div className="rec-detail-state">요건 분석 중…</div>}
                    {details[it.posting_id].error && (
                      <div className="rec-detail-state rec-detail-error">{details[it.posting_id].error}</div>
                    )}
                    {details[it.posting_id].matches &&
                      IMPORTANCE.map(([imp, label]) => {
                        const rows = details[it.posting_id].matches.filter((m) => m.importance === imp)
                        if (!rows.length) return null
                        return (
                          <div className="rec-req-group" key={imp}>
                            <span className={`rec-req-label rec-req-${imp}`}>{label}</span>
                            <div className="rec-req-items">
                              {rows.map((m, i) => (
                                <span className="rec-req-chip" key={`${m.text}-${i}`} title={m.fields.join(', ')}>
                                  {m.text}
                                </span>
                              ))}
                            </div>
                          </div>
                        )
                      })}
                    {details[it.posting_id].matches && details[it.posting_id].matches.length === 0 && (
                      <div className="rec-detail-state">추출된 요건이 없습니다.</div>
                    )}
                    <p className="rec-detail-note">공고 본문에서 규칙 기반으로 추출한 요건입니다(A11). 필드: 자격요건·직무내용·우대사항 등.</p>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* 2) 역량 갭 — 데모(C10 연계 전) */}
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h3>직무 역량 갭</h3>
            <p>C10 역량 갭 분석 연계 전 · 데모</p>
          </div>
          <span className="tiny-label">데모</span>
        </div>
        {GAP_DEMO.map((row) => (
          <div key={row.label} className="rec-gap-row">
            <div className="rec-gap-head">
              <span className="rec-gap-label">{row.label}</span>
              <span className="rec-gap-val">{row.value}% · 예시</span>
            </div>
            <div className="rec-bar">
              <div className="rec-bar-fill" style={{ width: `${row.value}%` }} />
            </div>
          </div>
        ))}
        <p className="rec-note">실제 역량 갭은 공고 요구 역량(C8)과 등록 경험의 근거 위치를 연결해야 하며, 추천 API 응답에는 포함되지 않습니다.</p>
      </section>
    </div>
  )
}
