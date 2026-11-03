// 저장된 로드맵 — [저장된 로드맵 (n)] 버튼 바로 아래에 펼쳐지는 팝오버. 사용자가 [저장]한 로드맵만 나온다.
// [열기] = 그 로드맵을 화면에 띄움, [삭제] = 확인 후 지움(되돌릴 수 없음).
// 바깥을 누르거나 Esc를 누르면 닫힌다. 열고 닫는 상태는 버튼(aria-expanded)과 같이 움직인다.

import { useEffect, useId, useRef, useState } from 'react'

const MODE_LABEL = { online: '온라인', offline: '오프라인' }

function when(iso) {
  const d = new Date(iso)
  return `${d.getFullYear()}.${d.getMonth() + 1}.${d.getDate()}`
}

export default function SavedRoadmapsPopover({ roadmaps, currentId, onOpen, onDelete }) {
  const [open, setOpen] = useState(false)
  const wrap = useRef(null)
  const panelId = useId()

  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (wrap.current && !wrap.current.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="lp-pop-wrap" ref={wrap}>
      <button
        type="button"
        className="c-btn-secondary lp-pop-btn"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        저장된 로드맵 ({roadmaps.length}) {open ? '▴' : '▾'}
      </button>

      {open && (
        <div id={panelId} className="lp-pop" role="region" aria-label="저장된 로드맵">
          {roadmaps.length === 0 ? (
            <p className="lp-cand-empty">저장한 로드맵이 없습니다. 로드맵을 만든 뒤 [저장]을 누르면 여기에 모입니다.</p>
          ) : (
            <ul className="lp-pop-list">
              {roadmaps.map((r) => {
                const items = r.items ?? []
                const done = items.filter((i) => i.status === 'done').length
                const posting = [r.company_name, r.posting_title].filter(Boolean).join(' ')
                return (
                  <li key={r.id} className={`lp-pop-item ${r.id === currentId ? 'on' : ''}`}>
                    <strong>{r.name || posting || '이름 없는 로드맵'}</strong>
                    {r.name && posting && <span className="lp-pop-sub">{posting}</span>}
                    <span className="lp-pop-sub">
                      {[MODE_LABEL[r.mode] ?? '전체', `주 ${r.weekly_hours}시간`, `${done}/${items.length} 완료`,
                        `${when(r.saved_at)} 저장`].join(' · ')}
                    </span>
                    <div className="lp-pop-actions">
                      <button
                        type="button"
                        className="c-btn-primary"
                        disabled={r.id === currentId}
                        onClick={() => {
                          onOpen(r.id)
                          setOpen(false)
                        }}
                      >
                        {r.id === currentId ? '보는 중' : '열기'}
                      </button>
                      <button type="button" className="c-btn-secondary lp-danger-btn" onClick={() => onDelete(r)}>
                        삭제
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
