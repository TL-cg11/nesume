import { useState } from 'react'

const split = (s) => s.split(',').map((x) => x.trim()).filter(Boolean)

const toForm = (e = {}) => ({
  title: e.title ?? '',
  type: e.type ?? '',
  period_start: e.period_start ?? '',
  period_end: e.period_end ?? '',
  role: e.role ?? '',
  tech_stack: (e.tech_stack ?? []).join(', '),
  outcome: e.outcome ?? '',
  detail: e.detail ?? '',
  tags: (e.tags ?? []).join(', '),
})

// spec 3.5 필드: 제목, 기간, 유형, 역할, 사용 기술, 성과, 상세 서술, 태그
export default function ExperienceForm({ initial, onSubmit, onCancel }) {
  const [f, setF] = useState(toForm(initial))
  const set = (k) => (ev) => setF({ ...f, [k]: ev.target.value })

  const submit = (ev) => {
    ev.preventDefault()
    onSubmit({
      title: f.title.trim(),
      type: f.type.trim(),
      period_start: f.period_start || null,
      period_end: f.period_end || null,
      role: f.role.trim() || null,
      tech_stack: split(f.tech_stack),
      outcome: f.outcome.trim() || null,
      detail: f.detail.trim() || null,
      tags: split(f.tags),
    })
  }

  return (
    <form className="exp-form" onSubmit={submit}>
      <label className="full">
        제목
        <input value={f.title} onChange={set('title')} maxLength={200} required />
      </label>
      <label>
        유형
        <input value={f.type} onChange={set('type')} maxLength={20} placeholder="프로젝트, 활동, 수상 등" required />
      </label>
      <label>
        역할
        <input value={f.role} onChange={set('role')} maxLength={200} />
      </label>
      <label>
        시작일
        <input type="date" value={f.period_start} onChange={set('period_start')} />
      </label>
      <label>
        종료일
        <input type="date" value={f.period_end} onChange={set('period_end')} />
      </label>
      <label className="full">
        사용 기술 (쉼표로 구분)
        <input value={f.tech_stack} onChange={set('tech_stack')} />
      </label>
      <label className="full">
        성과
        <textarea rows={2} value={f.outcome} onChange={set('outcome')} />
      </label>
      <label className="full">
        상세 서술
        <textarea rows={5} value={f.detail} onChange={set('detail')} />
      </label>
      <label className="full">
        태그 (쉼표로 구분)
        <input value={f.tags} onChange={set('tags')} />
      </label>
      <div className="full row">
        <button type="submit" disabled={!f.title.trim() || !f.type.trim()}>
          저장
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          취소
        </button>
      </div>
    </form>
  )
}
