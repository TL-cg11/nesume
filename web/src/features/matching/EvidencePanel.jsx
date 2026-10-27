// 대조할 내 쪽 근거 — 자소서 본문과 경험 (A11).
//
// ★ 경험은 **골라서** 보낸다. 가진 경험을 전부 보내면 "경험에는 있다"가 남발돼
//   정작 이 공고에 쓸 경험이 묻힌다. 서버 상한도 30개다 (MAX_EXPERIENCES).
//
// ★ 경험 목록·요약은 B5 모듈을 그대로 쓴다. 같은 변환을 여기서 또 만들면 B 가
//   필드를 바꿀 때 조용히 어긋난다 (`experienceSummary` 가 바로 그 변환용 함수다).
//
// ★ 경험 불러오기는 페이지의 `run` 을 쓰지 않고 **따로** 다룬다. 공고 분석과 오류 칸을
//   같이 쓰면 경험 조회가 실패했을 때 "공고를 찾을 수 없습니다" 가 떠 버린다
//   (실제로 그렇게 만들었다가 화면에서 보고 고쳤다). 딸린 조회의 실패는 그 자리에만 쓴다.
import { useEffect, useState } from 'react'
import { experiencesApi } from '../experiences/api.js'
import { experienceSummary } from '../experiences/summary.js'
import { MAX_EXPERIENCES, MAX_TERMS, MAX_TEXT_LEN } from './api.js'

export default function EvidencePanel({
  resumeText,
  onResumeTextChange,
  all,
  setAll,
  picked,
  onPickedChange,
  isBusy,
}) {
  const [loadFailed, setLoadFailed] = useState(false)

  // 처음 한 번만 불러온다.
  //
  // @B — `experiencesApi.list()` 는 opts 를 받지 않아 이 요청만 취소가 안 됩니다.
  //      다른 함수들처럼 `list(tags, opts)` 로 넘겨 주시면 가이드 5절대로 맞출 수 있습니다.
  //      지금은 떠난 뒤 setState 하지 않도록 플래그로 막습니다.
  useEffect(() => {
    if (all !== null) return
    let alive = true
    experiencesApi
      .list()
      .then((rows) => {
        if (alive) setAll(rows ?? [])
      })
      .catch(() => {
        if (!alive) return
        setLoadFailed(true)
        setAll([])
      })
    return () => {
      alive = false
    }
  }, [all, setAll])

  const toggle = (id) => {
    const next = new Set(picked)
    if (next.has(id)) next.delete(id)
    else if (next.size >= MAX_EXPERIENCES) return
    else next.add(id)
    onPickedChange(next)
  }

  const isFull = picked.size >= MAX_EXPERIENCES

  return (
    <div className="stack">
      <label className="stack">
        <span>지금 쓰고 있는 자소서 본문</span>
        <textarea
          className="mt-field"
          rows={8}
          value={resumeText}
          maxLength={MAX_TEXT_LEN}
          onChange={(e) => onResumeTextChange(e.target.value)}
          placeholder="아직 안 썼으면 비워 두십시오. 요건부터 먼저 볼 수 있습니다."
        />
        <span className="muted">
          {resumeText.length.toLocaleString()} / {MAX_TEXT_LEN.toLocaleString()}자
        </span>
      </label>

      <div className="stack">
        <div className="row">
          <strong className="grow">대조할 경험</strong>
          <span className="muted">
            {picked.size}/{MAX_EXPERIENCES} 선택
          </span>
        </div>

        {all === null ? (
          <p className="muted">불러오는 중...</p>
        ) : loadFailed ? (
          <p className="error">
            경험을 불러오지 못했습니다. 공고 요건은 그대로 분석할 수 있습니다.
          </p>
        ) : all.length === 0 ? (
          <p className="muted">
            저장된 경험이 없습니다. 경험 화면에서 먼저 등록하면 "경험에는 있는데 자소서에 안 쓴
            요건" 을 찾아 줍니다.
          </p>
        ) : (
          <ul className="list mt-exp">
            {all.map((e) => (
              <li key={e.id}>
                <label className="row">
                  <input
                    type="checkbox"
                    checked={picked.has(e.id)}
                    disabled={isBusy || (isFull && !picked.has(e.id))}
                    onChange={() => toggle(e.id)}
                  />
                  <span className="grow">
                    <strong>{e.title}</strong>
                    {e.tech_stack?.length > 0 && (
                      <span className="muted"> · {e.tech_stack.join(', ')}</span>
                    )}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {isFull && <p className="notice">경험은 한 번에 {MAX_EXPERIENCES}개까지 보냅니다.</p>}
      </div>
    </div>
  )
}

// 고른 경험을 서버 스키마(ExperienceIn)로 바꾼다. 페이지가 보낼 때 쓴다.
export function toExperienceIn(all, picked) {
  return (all ?? [])
    .filter((e) => picked.has(e.id))
    .map((e) => ({
      label: e.title,
      text: experienceSummary(e),
      // tech_stack + tags 를 합쳐 보낸다 (schemas.py ExperienceIn.terms 주석).
      // 상한을 넘기면 서버가 422 로 거절하므로 여기서 자른다
      terms: [...new Set([...(e.tech_stack ?? []), ...(e.tags ?? [])])].slice(0, MAX_TERMS),
    }))
}
