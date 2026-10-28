import { useEffect, useRef, useState } from 'react'
import ShareTags from './ShareTags.jsx'

// 버전 버튼(10/28): 문항 제목 옆 "v5 (최신) ▾" → 펼치면 버전 목록. 행 클릭 = 불러오기, 마우스 올리면 × = 삭제
export default function VersionMenu({ versions, loadedId, max, showEnded, onToggleEnded, onOpen, onDelete }) {
  const [open, setOpen] = useState(false)
  const box = useRef(null)

  // 바깥 클릭·Esc로 닫기
  useEffect(() => {
    if (!open) return
    const onDown = (e) => box.current && !box.current.contains(e.target) && setOpen(false)
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const current = versions.find((v) => v.id === loadedId)
  const label = !versions.length
    ? '저장된 버전 없음'
    : current
      ? `v${current.version_no}${current.id === versions[0].id ? ' (최신)' : ''}`
      : '버전'

  return (
    <div className="ver-menu" ref={box}>
      <button type="button" className="secondary ver-menu-btn" onClick={() => setOpen((o) => !o)}
        aria-expanded={open} aria-haspopup="true" disabled={!versions.length}>
        {label} <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="ver-pop" role="menu">
          <div className="ver-pop-head">
            <strong>버전 기록</strong>
            <span className="muted">{versions.length}/{max}</span>
            <label className="muted">
              <input type="checkbox" checked={showEnded} onChange={(e) => onToggleEnded(e.target.checked)} /> 지난 공유 보기
            </label>
          </div>
          <ul className="timeline">
            {versions.map((v) => (
              <li key={v.id} className={loadedId === v.id ? 'on' : undefined}>
                {/* 버전명·행 빈 곳을 누르면 불러오기(덮개). 공유 태그·삭제는 덮개 위라 따로 동작 */}
                <button type="button" className="ver-open" onClick={() => { onOpen(v); setOpen(false) }}>
                  v{v.version_no}
                </button>
                <span className="muted">
                  {v.source === 'ai' ? 'AI' : '수동'}
                  {v.restored_from && ` · v${versions.find((x) => x.id === v.restored_from)?.version_no ?? '?'}에서 복원`}
                  {' · '}
                  {v.char_count.toLocaleString()}자 · {new Date(v.created_at).toLocaleString()}
                </span>
                <ShareTags shares={v.shares} />
                <button type="button" className="ver-delete" onClick={() => onDelete(v)}
                  aria-label={`v${v.version_no} 삭제`} title="삭제">×</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
