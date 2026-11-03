import ShareTags from './ShareTags.jsx'

// 버전 관리 탭의 버전 목록(10/29). 행 클릭 = 미리보기 선택, 마우스 올리면 × = 삭제. 편집 중인 버전은 표시
export default function VersionList({ versions, selectedId, loadedId, onSelect, onDelete }) {
  if (!versions.length) return <p className="muted">저장된 버전이 없습니다.</p>
  return (
    <div className="card ver-list-card">
      <ul className="timeline">
        {versions.map((v) => (
          <li key={v.id} className={selectedId === v.id ? 'on' : undefined}>
            {/* 버전명·행 빈 곳을 누르면 미리보기(덮개). 공유 태그·삭제는 덮개 위라 따로 동작 */}
            <button type="button" className="ver-open" onClick={() => onSelect(v)}>
              v{v.version_no}
            </button>
            {v.id === versions[0].id && <span className="ver-badge">최신</span>}
            {v.id === loadedId && <span className="ver-badge editing">편집 중</span>}
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
  )
}
