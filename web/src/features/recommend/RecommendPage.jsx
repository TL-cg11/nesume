import { useEffect, useState } from 'react'
import { recommendApi } from './api.js'
import { applicationsApi } from '../applications/api.js'
import { ApiError } from '../../app/api/client.js'
import { safeUrl } from '../safeUrl.js'
import '../c-common.css'
import './recommend.css'

// 출처 문구 — 서울시 공고는 "서울특별시 공공데이터" 표시가 약관상 의무(Plan.md 6절).
const SOURCE_LABEL = { seoul: '서울특별시 공공데이터', work24_open: '고용24 공채속보' }


const pct = (v) => `${Math.round((v ?? 0) * 100)}%`


// 공고 상세 — 공고에 적힌 글 그대로(`라벨: 값` + 직무내용 원문). 외부 텍스트라 HTML로 렌더링하지 않는다.
function PostingDetail({ posting }) {
  const refOnly = /모집요강\s*참조|상세\s*요강\s*참조/.test(posting.job_content || '')
  return (
    <div className="rec-posting">
      {posting.fields.length > 0 && (
        <dl className="rec-posting-fields">
          {posting.fields.map((f) => (
            <div className="rec-posting-row" key={f.label}>
              <dt>{f.label}</dt>
              <dd>{f.value.replace(/\s*\|\s*/g, ' · ')}</dd>
            </div>
          ))}
        </dl>
      )}
      {posting.job_content && (
        <div className="rec-posting-body">
          <span className="rec-posting-body-label">직무내용</span>
          <p>{posting.job_content}</p>
        </div>
      )}
      {(refOnly || !posting.job_content) && (
        <p className="rec-detail-note">
          상세 모집요강은 기업 채용 페이지(원문)에서 확인해 주세요{safeUrl(posting.url) ? ' — 아래 "지원하기 ↗"' : ''}.
        </p>
      )}
    </div>
  )
}

// [B 추가 10/29] 자소서 상세 '공고 추천' 탭에 넣을 때: resumeId = 그 자소서 기준 추천(서버 resume_id), embedded = 제목 숨김.
// 둘 다 생략하면 기존 /recommend 화면과 똑같이 동작한다.
export default function RecommendPage({ resumeId = null, embedded = false }) {
  const [heldText, setHeldText] = useState('')
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
    if (cur?.posting) {
      setDetails((d) => ({ ...d, [id]: { ...cur, open: true } }))
      return
    }
    setDetails((d) => ({ ...d, [id]: { open: true, loading: true } }))
    try {
      const data = await recommendApi.postingDetail(id)
      setDetails((d) => ({ ...d, [id]: { open: true, loading: false, posting: data } }))
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
    e?.preventDefault()
    setLoading(true)
    setError(null)
    try {
      // [B 10/29] 자소서 기준이면 역량은 서버가 그 자소서에서 뽑는다(resume_id → gather_evidence). 입력값은 쓰지 않음
      const held_keys = resumeId ? [] : heldText
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      const data = await recommendApi.recommend({
        held_keys,
        region_codes: [],
        job_codes: [],
        top_k: 20,
        ...(resumeId ? { resume_id: resumeId } : {}),
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

  // [B 10/29] 자소서 기준이면 탭을 열 때 바로 추천한다
  useEffect(() => {
    if (resumeId) run()
    // resumeId가 바뀔 때만 다시 추천(run은 매번 새로 만들어지므로 의존성에서 뺀다)
  }, [resumeId])

  return (
    <div className="rec-page">
      {!embedded && (
        <div>
          <p className="c-eyebrow">CAREER MATCH</p>
          <h1 className="c-page-heading">공고 추천 · 역량 분석</h1>
          <p className="c-page-subtitle">보유 역량을 넣으면 맞춤 공고를 추천합니다.</p>
        </div>
      )}

      {resumeId ? (
        <div className="c-panel rec-form-grid">
          <p className="rec-form-wide">열려 있는 자기소개서의 내용과 연결한 경험을 바탕으로 맞는 공고를 찾습니다.</p>
          <button className="c-btn-primary c-btn-full" type="button" onClick={() => run()} disabled={loading}>
            {loading ? '분석 중…' : '다시 추천'}
          </button>
        </div>
      ) : (
      <form className="c-panel" onSubmit={run}>
        <div className="rec-form-grid">
          <div className="rec-form-wide">
            <label className="c-field-label" htmlFor="rec-held">보유 역량 (쉼표로 구분)</label>
            <input
              id="rec-held"
              className="field"
              value={heldText}
              onChange={(e) => setHeldText(e.target.value)}
              placeholder="예: Python, SQL, AWS — 쉼표로 구분"
            />
          </div>
          <button className="c-btn-primary c-btn-full" type="submit" disabled={loading}>
            {loading ? '분석 중…' : '맞춤 분석 실행'}
          </button>
        </div>
      </form>
      )}

      {/* 1) 추천 공고 목록 — 실제 /recommendations 응답 */}
      <section className="c-panel">
        <div className="c-panel-heading">
          <div>
            <h3>추천 공고</h3>
            {/* [B 10/29] 자소서 탭 안에서는 개발용 설명을 숨긴다 */}
            {!embedded && <p>POST /recommendations · 점수 = 0.5 벡터 + 0.5 키워드율</p>}
          </div>
          {result && !result.cold_start && (
            <span className="c-tiny-label">{result.items.length}건</span>
          )}
        </div>

        {loading && <div className="rec-state">불러오는 중…</div>}

        {!loading && error && (
          <div className="rec-state rec-state-error">
            <strong className="rec-state-title">추천을 불러오지 못했습니다</strong>
            <p>{error}</p>
          </div>
        )}

        {!loading && !error && result === null && (
          <div className="rec-state">{resumeId ? '추천을 준비하고 있습니다.' : <>보유 역량을 넣고 <strong>맞춤 분석 실행</strong>을 눌러 주세요.</>}</div>
        )}

        {!loading && !error && result?.cold_start && (
          <div className="rec-state">
            <strong className="rec-state-title">아직 추천할 공고가 없어요</strong>
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
                <p className="rec-item-job">
                  {it.posting?.company_name && <b className="rec-item-company">{it.posting.company_name}</b>}
                  {it.posting?.company_name && ' · '}
                  {it.posting?.job_name ?? '직무 미상'}
                </p>
                {SOURCE_LABEL[it.posting?.source] && (
                  <p className="rec-item-source">출처: {SOURCE_LABEL[it.posting.source]}</p>
                )}
                <div className="rec-item-meta">
                  <span className="rec-chip rec-chip-vec">벡터 {pct(it.vector_score)}</span>
                  {it.keyword_available === false ? (
                    // 공고에 비교할 기술 키워드가 없음 — 0%(안 맞음)와 구분
                    <span className="rec-chip rec-chip-kw" title="공고에서 비교할 기술 키워드를 찾지 못해 문맥(벡터) 점수로만 추천했어요">
                      키워드 정보 없음
                    </span>
                  ) : (
                    <span className="rec-chip rec-chip-kw">키워드 {pct(it.keyword_score)}</span>
                  )}
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
                  <button className="c-btn-secondary rec-detail-btn" onClick={() => toggleDetail(it.posting_id)}>
                    {details[it.posting_id]?.open ? '상세 접기 ▴' : '상세 보기 ▾'}
                  </button>
                  {appliedIds.has(it.posting_id) ? (
                    <span className="rec-applied">✓ 지원 현황에 추가됨</span>
                  ) : (
                    <button
                      className="c-btn-secondary rec-track-btn"
                      onClick={() => applyTo(it)}
                      disabled={applyingId === it.posting_id}
                    >
                      {applyingId === it.posting_id ? '추가 중…' : '지원 현황에 추가'}
                    </button>
                  )}
                  {safeUrl(it.posting?.url) ? (
                    <a
                      className="c-btn-primary rec-apply-btn rec-link-btn"
                      href={safeUrl(it.posting.url)}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="기업 채용 페이지(외부 사이트)로 이동합니다"
                    >
                      지원하기 ↗ <span className="rec-link-ext">외부 사이트</span>
                    </a>
                  ) : (
                    <button className="c-btn-primary rec-apply-btn" disabled title="이 공고는 원문 링크가 없습니다">
                      원문 링크 없음
                    </button>
                  )}
                </div>

                {details[it.posting_id]?.open && (
                  <div className="rec-detail">
                    {details[it.posting_id].loading && <div className="rec-detail-state">공고 불러오는 중…</div>}
                    {details[it.posting_id].error && (
                      <div className="rec-detail-state rec-detail-error">{details[it.posting_id].error}</div>
                    )}
                    {details[it.posting_id].posting && <PostingDetail posting={details[it.posting_id].posting} />}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

    </div>
  )
}
