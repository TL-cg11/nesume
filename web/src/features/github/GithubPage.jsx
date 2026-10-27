import { Fragment, useState } from 'react'
import { Link } from 'react-router'
import { errorText, githubApi } from './api.js'
import './github.css'

// B14 GitHub 프로젝트 소개(spec 3.4, part2_guide 4.60)
// 공개 저장소 주소 → README·언어 비율·커밋 수 → 배경·역할·기술·성과 초안 → 고친 뒤 경험 데이터로 저장
const SECTIONS = ['배경', '역할', '기술', '성과']
const split = (s) => s.split(',').map((x) => x.trim()).filter(Boolean)

const toForm = (e) => ({
  title: e.title ?? '',
  type: e.type ?? '',
  role: e.role ?? '',
  tech_stack: (e.tech_stack ?? []).join(', '),
  outcome: e.outcome ?? '',
  detail: e.detail ?? '',
  tags: (e.tags ?? []).join(', '),
})

function ExperienceDraft({ initial, onSaved }) {
  const [f, setF] = useState(toForm(initial))
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (ev) => setF({ ...f, [k]: ev.target.value })

  const submit = async (ev) => {
    ev.preventDefault()
    setBusy(true)
    try {
      await githubApi.saveExperience({
        title: f.title.trim(), type: f.type.trim(), period_start: null, period_end: null,
        role: f.role.trim() || null, tech_stack: split(f.tech_stack), outcome: f.outcome.trim() || null,
        detail: f.detail.trim() || null, tags: split(f.tags),
      })
      setError(null)
      onSaved()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="gh-form card" onSubmit={submit}>
      <h2 className="gh-full">경험 데이터로 저장</h2>
      <p className="gh-full muted">초안 내용을 채워 두었습니다. 고친 뒤 저장하세요. 기간은 경험 데이터 화면에서 추가할 수 있습니다.</p>
      <label className="gh-full">제목<input value={f.title} onChange={set('title')} maxLength={200} required /></label>
      <label>유형<input value={f.type} onChange={set('type')} maxLength={20} required /></label>
      <label>역할<input value={f.role} onChange={set('role')} maxLength={200} /></label>
      <label className="gh-full">사용 기술 (쉼표로 구분)<input value={f.tech_stack} onChange={set('tech_stack')} /></label>
      <label className="gh-full">성과<textarea rows={2} value={f.outcome} onChange={set('outcome')} /></label>
      <label className="gh-full">상세 서술<textarea rows={6} value={f.detail} onChange={set('detail')} /></label>
      <label className="gh-full">태그 (쉼표로 구분)<input value={f.tags} onChange={set('tags')} /></label>
      {error && <p className="gh-full error">{error}</p>}
      <div className="gh-full row">
        <button type="submit" disabled={busy || !f.title.trim() || !f.type.trim()}>저장</button>
      </div>
    </form>
  )
}

export default function GithubPage() {
  const [repo, setRepo] = useState('')
  const [role, setRole] = useState('')
  const [tech, setTech] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [formKey, setFormKey] = useState(0) // 다시 생성하면 저장 폼도 새 초안으로

  const generate = async (ev) => {
    ev?.preventDefault()
    setBusy(true)
    setSaved(false)
    try {
      const r = await githubApi.draft({ repo_url: repo.trim(), role: role.trim(), tech: split(tech).slice(0, 10) })
      setResult(r)
      setFormKey((k) => k + 1)
      setError(null)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const r = result?.repo
  return (
    <section className="stack">
      <h1>GitHub 프로젝트 소개</h1>
      <p className="muted">공개 저장소 주소 → README·언어 비율·커밋 수 → 소개 초안. 공개 저장소만 지원하며 토큰은 받지 않습니다.</p>

      <form className="card gh-input" onSubmit={generate}>
        <input name="repo" value={repo} onChange={(e) => setRepo(e.target.value)} maxLength={300}
          placeholder="https://github.com/소유자/저장소" aria-label="저장소 주소" required />
        <input value={role} onChange={(e) => setRole(e.target.value)} maxLength={200}
          placeholder="강조할 역할 (선택)" aria-label="강조할 역할" />
        <input value={tech} onChange={(e) => setTech(e.target.value)}
          placeholder="강조할 기술, 쉼표로 구분 (선택)" aria-label="강조할 기술" />
        <button type="submit" disabled={busy || !repo.trim()}>{busy ? '생성 중…' : '생성'}</button>
      </form>
      {error && <p className="error">{error}</p>}

      {result && (
        <div className="card">
          <div className="gh-stats">
            <a className="gh-repo" href={r.html_url} target="_blank" rel="noreferrer">{r.full_name}</a>
            <span className="muted">
              {r.languages.slice(0, 3).map((l) => `${l.name} ${l.percent}%`).join(' · ') || '언어 정보 없음'}
              {` · 커밋 ${r.commits} · 기여자 ${r.contributors}`}
            </span>
          </div>
          {result.llm_unavailable && <p className="notice">AI 모델이 연결되지 않아 저장소 정보로 기본 틀만 채웠습니다.</p>}
          {result.blocked_reason && <p className="notice">보안 정책으로 초안을 만들지 못했습니다. 저장소 정보로 기본 틀만 채웠습니다.</p>}
          {result.readme_flags.length > 0 && <p className="muted">README의 지시문으로 보이는 문장은 제외하고 사용했습니다.</p>}
          <dl className="gh-sections">
            {SECTIONS.map((k) => (
              <Fragment key={k}>
                <dt>{k}</dt>
                <dd>{result.sections[k] || <span className="muted">(비어 있음)</span>}</dd>
              </Fragment>
            ))}
          </dl>
          {result.questions.length > 0 && (
            <>
              <p className="notice">README가 없거나 짧아 저장소 통계로만 만들었습니다. 아래 질문에 답해 내용을 채워 주세요.</p>
              <ol className="gh-questions">{result.questions.map((q) => <li key={q}>{q}</li>)}</ol>
            </>
          )}
          <div className="row">
            <button type="button" className="secondary" onClick={generate} disabled={busy}>다시 생성</button>
          </div>
        </div>
      )}

      {result && !saved && (
        <ExperienceDraft key={formKey} initial={result.experience_draft} onSaved={() => setSaved(true)} />
      )}
      {saved && (
        <p className="success">경험 데이터로 저장했습니다. <Link to="/experiences">경험 데이터 보기</Link></p>
      )}
    </section>
  )
}
