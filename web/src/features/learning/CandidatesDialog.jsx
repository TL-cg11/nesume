// "이 역량 강좌 전체 보기" — 로드맵 항목 역량에 맞는 강좌를 개수 제한 없이 페이지로 본다(docs/C14.md).
//
// 정렬은 서버가 로드맵과 같은 기준(수료증 → 평점 → 시간)으로 한다. 여기서는 학습 방법 필터·페이지만 고른다.
// [로드맵에 추가] = 같은 역량·같은 주차에 새 항목, [이걸로 교체] = 이 항목의 강좌만 바꿈(주차·완료 상태 유지).
// 강좌 링크는 서버 DB 값(수집 시 https 출처 검증)만 쓰고, 새 탭 + noopener 로 연다.
//
// 브라우저 기본 <dialog> 를 모달로 연다 — 포커스 가두기·Esc 닫기를 브라우저가 해 준다.

import { useCallback, useEffect, useRef, useState } from 'react'
import { roadmapsApi } from './api.js'
import { ApiError } from '../../app/api/client.js'

const PAGE_SIZE = 20
const MODE_LABEL = { online: '온라인', offline: '오프라인' }
const SOURCE_LABEL = { kmooc: 'K-MOOC', work24: '고용24' }
const RATING_MAX = { kmooc: 5, work24: 100 }

function rating(c) {
  if (c.rating == null) return null
  const max = RATING_MAX[c.source]
  return max ? `평점 ${c.rating}/${max}` : `평점 ${c.rating}`
}

export default function CandidatesDialog({ roadmapId, item, onClose, onPicked }) {
  const ref = useRef(null)
  const [mode, setMode] = useState('') // '' = 전체
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null) // 처리 중인 content_id

  useEffect(() => {
    const dialog = ref.current
    if (dialog && item && !dialog.open) dialog.showModal()
  }, [item])

  const load = useCallback(
    async (signal) => {
      setError(null)
      try {
        const res = await roadmapsApi.candidates(roadmapId, item.id, { mode, page, size: PAGE_SIZE }, { signal })
        if (!signal?.aborted) setData(res)
      } catch (e) {
        if (e.name === 'AbortError') return
        setError(e instanceof ApiError ? e.message : '강좌 목록을 불러오지 못했습니다.')
      }
    },
    [roadmapId, item, mode, page],
  )

  useEffect(() => {
    const ctrl = new AbortController()
    setData(null)
    load(ctrl.signal)
    return () => ctrl.abort()
  }, [load])

  const pick = async (c, replace) => {
    setBusy(c.content_id)
    try {
      const saved = await roadmapsApi.pick(roadmapId, item.id, { content_id: c.content_id, replace })
      onPicked(saved, replace)
      if (replace) {
        ref.current?.close()
      } else {
        setData((d) => ({
          ...d,
          items: d.items.map((x) => (x.content_id === c.content_id ? { ...x, in_roadmap: true } : x)),
        }))
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '로드맵에 반영하지 못했습니다.')
    } finally {
      setBusy(null)
    }
  }

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <dialog ref={ref} className="lp-cand-dialog" onClose={onClose} aria-labelledby="lp-cand-title">
      <div className="lp-cand-head">
        <h3 id="lp-cand-title">{item.gap_label ?? item.gap_key} 강좌 전체</h3>
        <button type="button" className="lp-cand-close" aria-label="닫기" onClick={() => ref.current?.close()}>
          ×
        </button>
      </div>

      <div className="lp-cand-filter" role="group" aria-label="학습 방법">
        {[['', '전체'], ['online', '온라인'], ['offline', '오프라인']].map(([v, label]) => (
          <button
            key={v || 'all'}
            type="button"
            className={mode === v ? 'on' : ''}
            onClick={() => {
              setMode(v)
              setPage(1)
            }}
          >
            {label}
          </button>
        ))}
        {data && <span className="lp-cand-count">{data.total}개 · 평점순</span>}
      </div>

      {error && <p className="lp-cand-error">{error}</p>}
      {!data && !error && <p className="lp-cand-empty">불러오는 중…</p>}
      {data && data.items.length === 0 && <p className="lp-cand-empty">맞는 강좌가 없습니다.</p>}

      {data && data.items.length > 0 && (
        <ul className="lp-cand-list">
          {data.items.map((c) => (
            <li key={c.content_id} className="lp-cand-item">
              <div className="lp-cand-main">
                <div className="lp-cand-title-row">
                  <span className={`c-lesson-mode c-mode-${c.mode}`}>{MODE_LABEL[c.mode] ?? c.mode}</span>
                  {c.match_kind === 'semantic' && <span className="lp-ai-badge">AI 추천 · 관련도 낮을 수 있음</span>}
                  <strong>{c.title}</strong>
                </div>
                <p className="lp-cand-meta">
                  {[SOURCE_LABEL[c.source] ?? c.source, c.provider, c.hours != null && `${c.hours}h`,
                    c.weeks != null && `${c.weeks}주`, rating(c), c.certificate && '수료증']
                    .filter(Boolean)
                    .join(' · ')}
                </p>
                <a className="c-lesson-link" href={c.url} target="_blank" rel="noopener noreferrer">
                  강좌 열기 ↗ (외부 사이트)
                </a>
              </div>
              <div className="lp-cand-actions">
                {c.content_id === item.content_id ? (
                  <span className="lp-cand-tag">지금 강좌</span>
                ) : (
                  <>
                    <button type="button" className="c-btn-primary" disabled={busy !== null} onClick={() => pick(c, true)}>
                      이걸로 교체
                    </button>
                    <button
                      type="button"
                      className="c-btn-secondary"
                      disabled={busy !== null || c.in_roadmap}
                      onClick={() => pick(c, false)}
                    >
                      {c.in_roadmap ? '로드맵에 있음' : '로드맵에 추가'}
                    </button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {data && pages > 1 && (
        <div className="lp-cand-pager">
          <button type="button" className="c-btn-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            이전
          </button>
          <span>
            {page} / {pages}
          </span>
          <button type="button" className="c-btn-secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            다음
          </button>
        </div>
      )}
    </dialog>
  )
}
