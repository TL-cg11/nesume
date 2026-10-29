import { useState } from 'react'
import { experiencesApi } from './api.js'
import { TEMPLATES, TYPES, fromMonth, normalizeType, toMonth } from './templates.js'

const split = (s) => s.split(',').map((x) => x.trim()).filter(Boolean)

const toForm = (e = {}) => ({
  title: e.title ?? '',
  type: e.type ? normalizeType(e.type) : '프로젝트',
  period_start: toMonth(e.period_start),
  period_end: toMonth(e.period_end),
  role: e.role ?? '',
  tech_stack: (e.tech_stack ?? []).join(', '),
  outcome: e.outcome ?? '',
  detail: e.detail ?? '',
  tags: (e.tags ?? []).join(', '),
})

const githubError = (e) => {
  if (e.code === 'github_rate_limited') return 'GitHub 조회 한도를 넘었습니다. 잠시 후 다시 시도해 주세요.'
  if (e.code === 'github_unavailable') return 'GitHub에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'
  return e.message
}

// 유형 GitHub: 공개 저장소 → README·언어·커밋 → 초안으로 폼 채우기(B14, 10/28 경험 화면으로 이동)
function GithubDraft({ onDraft }) {
  const [repo, setRepo] = useState('')
  const [role, setRole] = useState('')
  const [tech, setTech] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const generate = async () => {
    setBusy(true)
    try {
      const r = await experiencesApi.githubDraft({ repo_url: repo.trim(), role: role.trim(), tech: split(tech).slice(0, 10) })
      setResult(r)
      setError(null)
      onDraft(r.experience_draft)
    } catch (e) {
      setError(githubError(e))
    } finally {
      setBusy(false)
    }
  }

  const r = result?.repo
  return (
    <div className="full exp-github">
      <p className="muted">공개 저장소 주소로 소개 초안을 만들어 아래 칸을 채웁니다. 토큰은 받지 않습니다.</p>
      <div className="exp-github-input">
        <input value={repo} onChange={(e) => setRepo(e.target.value)} maxLength={300}
          placeholder="https://github.com/소유자/저장소" aria-label="저장소 주소" />
        <input value={role} onChange={(e) => setRole(e.target.value)} maxLength={200}
          placeholder="강조할 역할 (선택)" aria-label="강조할 역할" />
        <input value={tech} onChange={(e) => setTech(e.target.value)}
          placeholder="강조할 기술, 쉼표로 구분 (선택)" aria-label="강조할 기술" />
        <button type="button" onClick={generate} disabled={busy || !repo.trim()}>
          {busy ? '생성 중…' : result ? '다시 생성' : '초안 생성'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <>
          <p className="muted">
            <a href={r.html_url} target="_blank" rel="noreferrer">{r.full_name}</a>
            {` · ${r.languages.slice(0, 3).map((l) => `${l.name} ${l.percent}%`).join(' · ') || '언어 정보 없음'}`}
            {` · 커밋 ${r.commits} · 기여자 ${r.contributors}`}
          </p>
          {result.llm_unavailable && <p className="notice">AI 모델이 연결되지 않아 저장소 정보로 기본 틀만 채웠습니다.</p>}
          {result.blocked_reason && <p className="notice">보안 정책으로 초안을 만들지 못해 기본 틀만 채웠습니다.</p>}
          {result.questions.length > 0 && (
            <div className="notice">
              README가 없거나 짧아 통계로만 만들었습니다. 아래 질문의 답으로 내용을 채워 주세요.
              <ol>{result.questions.map((q) => <li key={q}>{q}</li>)}</ol>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// spec 3.5 필드: 제목, 기간, 유형, 역할, 사용 기술, 성과, 상세 서술, 태그. 유형에 따라 칸 이름·예시·표시가 바뀐다
export default function ExperienceForm({ initial, onSubmit, onCancel }) {
  const [f, setF] = useState(toForm(initial))
  const set = (k) => (ev) => setF({ ...f, [k]: ev.target.value })
  const t = TEMPLATES[f.type]

  // GitHub 초안: 사용자가 이미 쓴 칸은 덮지 않고 빈 칸만 채운다(기간·유형은 그대로)
  const applyDraft = (d) =>
    setF((cur) => {
      const draft = toForm({ ...d, type: 'GitHub' })
      const merged = { ...cur }
      for (const k of ['title', 'role', 'tech_stack', 'outcome', 'detail', 'tags']) {
        if (!cur[k].trim()) merged[k] = draft[k]
      }
      return merged
    })

  const submit = (ev) => {
    ev.preventDefault()
    const start = fromMonth(f.period_start)
    onSubmit({
      title: f.title.trim(),
      type: f.type,
      period_start: start,
      period_end: t.period === 'single' ? start : fromMonth(f.period_end),
      role: f.role.trim() || null,
      tech_stack: t.tech ? split(f.tech_stack) : [], // 숨긴 칸 값은 저장하지 않는다
      outcome: f.outcome.trim() || null,
      detail: f.detail.trim() || null,
      tags: split(f.tags),
    })
  }

  const badRange = t.period === 'range' && f.period_start && f.period_end && f.period_end < f.period_start

  return (
    <form className="exp-form card" onSubmit={submit}>
      <label>
        유형
        <select value={f.type} onChange={set('type')}>
          {TYPES.map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
      </label>
      <span />
      {f.type === 'GitHub' && <GithubDraft onDraft={applyDraft} />}
      <label className="full">
        {t.title.label}
        <input value={f.title} onChange={set('title')} maxLength={200} placeholder={t.title.placeholder} required />
      </label>
      {t.period === 'single' ? (
        <label>
          수상일
          <input type="month" value={f.period_start} onChange={set('period_start')} min="1900-01" max="9999-12" />
        </label>
      ) : (
        <>
          <label>
            시작
            <input type="month" value={f.period_start} onChange={set('period_start')} min="1900-01" max="9999-12" />
          </label>
          <label>
            종료
            <input type="month" value={f.period_end} onChange={set('period_end')} min="1900-01" max="9999-12" />
          </label>
        </>
      )}
      <label className={t.period === 'single' ? '' : 'full'}>
        {t.role.label}
        <input value={f.role} onChange={set('role')} maxLength={200} placeholder={t.role.placeholder} />
      </label>
      {badRange && <p className="full error">종료가 시작보다 앞섭니다.</p>}
      {t.tech && (
        <label className="full">
          사용 기술 (쉼표로 구분)
          <input value={f.tech_stack} onChange={set('tech_stack')} placeholder="예: FastAPI, PostgreSQL, Redis" />
        </label>
      )}
      <label className="full">
        {t.outcome.label}
        <textarea rows={2} value={f.outcome} onChange={set('outcome')} placeholder={t.outcome.placeholder} />
      </label>
      <label className="full">
        {t.detail.label}
        <textarea rows={6} value={f.detail} onChange={set('detail')} placeholder={t.detail.placeholder} />
      </label>
      <label className="full">
        태그 (쉼표로 구분)
        <input value={f.tags} onChange={set('tags')} placeholder="예: 협업, 성능 개선" />
      </label>
      <div className="full row">
        <button type="submit" disabled={!f.title.trim() || badRange}>
          저장
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          취소
        </button>
      </div>
    </form>
  )
}
