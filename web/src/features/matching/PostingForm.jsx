// 공고 입력 (A11). 공고를 받는 길은 두 가지고, **하나만** 쓴다.
//
//   붙여넣기   화면이 들고 있는 값을 그대로 보낸다 (posting)
//   저장된 공고 C4 창구로 서버가 읽는다 (posting_id)
//
// ★ 지금은 붙여넣기가 기본이다. C 의 공고 목록 화면이 생기면 거기서 "이 공고로 분석"
//   으로 넘어오며 posting_id 를 채우는 쪽이 맞다. 그때까지 UUID 를 손으로 넣는 길도
//   열어 둔다 — 저장된 공고로도 분석이 되는지 확인할 방법이 있어야 한다.
import { MAX_FIELD_LEN, POSTING_FIELDS } from './api.js'

export default function PostingForm({ mode, onModeChange, posting, onChange, postingId, onPostingIdChange }) {
  const change = (name, value) => onChange({ ...posting, [name]: value })

  return (
    <div className="stack">
      <div className="mt-modes" role="radiogroup" aria-label="공고를 받는 방법">
        <button
          role="radio"
          aria-checked={mode === 'paste'}
          className={mode === 'paste' ? 'mt-mode on' : 'mt-mode'}
          onClick={() => onModeChange('paste')}
        >
          공고 붙여넣기
        </button>
        <button
          role="radio"
          aria-checked={mode === 'saved'}
          className={mode === 'saved' ? 'mt-mode on' : 'mt-mode'}
          onClick={() => onModeChange('saved')}
        >
          저장된 공고
        </button>
      </div>

      {mode === 'saved' ? (
        <label className="stack">
          <span>공고 ID</span>
          <input
            value={postingId}
            onChange={(e) => onPostingIdChange(e.target.value)}
            placeholder="예: 3f0c1b7a-5e21-4a9d-9c3e-0b8f6d2a1e44"
            aria-describedby="mt-posting-id-help"
          />
          <span id="mt-posting-id-help" className="muted">
            저장해 둔 공고를 서버가 읽습니다. 없는 공고와 열람 권한이 없는 공고는 똑같이
            "찾을 수 없습니다" 로 답합니다.
          </span>
        </label>
      ) : (
        <>
          {POSTING_FIELDS.map(({ name, label, rows }) => (
            <label key={name} className="stack">
              <span>{label}</span>
              {rows > 1 ? (
                <textarea
                  className="mt-field"
                  rows={rows}
                  value={posting[name] ?? ''}
                  maxLength={MAX_FIELD_LEN}
                  onChange={(e) => change(name, e.target.value)}
                />
              ) : (
                <input
                  value={posting[name] ?? ''}
                  maxLength={MAX_FIELD_LEN}
                  onChange={(e) => change(name, e.target.value)}
                />
              )}
            </label>
          ))}
          <p className="muted">
            아는 칸만 채우면 됩니다. 요건은 주로 담당 업무·자격 요건과 우대 사항에서 나옵니다.
          </p>
        </>
      )}
    </div>
  )
}
