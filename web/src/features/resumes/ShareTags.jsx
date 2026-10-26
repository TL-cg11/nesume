import { useState } from 'react'

// 버전에 붙는 멘토 공유 태그(B10, part2_guide 4.43)
// 유효한 공유는 2명까지 펼치고 3명 이상이면 "외 N명"으로 접는다. 지난 공유는 흐리게.
const FOLD_AT = 2
const STATUS_TEXT = { expired: '만료', revoked: '취소' }

export const shortDate = (iso) => {
  const [, m, d] = iso.split('-')
  return `${Number(m)}/${Number(d)}`
}

export default function ShareTags({ shares }) {
  const [open, setOpen] = useState(false)
  if (!shares?.length) return null
  const active = shares.filter((s) => s.status === 'active')
  const ended = shares.filter((s) => s.status !== 'active')
  const shown = open || active.length <= FOLD_AT ? active : active.slice(0, 1)
  const hidden = active.length - shown.length

  return (
    <span className="share-tags">
      {shown.map((s) => (
        <span key={s.share_id} className="share-tag" title={`${s.mentor_label} · ${s.end_date}까지 공유`}>
          <span className="share-tag-mark">공유</span>
          {s.mentor_label} ~{shortDate(s.end_date)}
        </span>
      ))}
      {hidden > 0 && (
        <button className="link share-more" onClick={() => setOpen(true)} aria-expanded={open}>
          외 {hidden}명 ▾
        </button>
      )}
      {open && active.length > FOLD_AT && (
        <button className="link share-more" onClick={() => setOpen(false)} aria-expanded={open}>
          접기 ▴
        </button>
      )}
      {ended.map((s) => (
        <span key={s.share_id} className="share-tag ended" title={`${STATUS_TEXT[s.status]}된 공유`}>
          {s.mentor_label} {shortDate(s.ended_on)} {STATUS_TEXT[s.status]}
        </span>
      ))}
    </span>
  )
}
