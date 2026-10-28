// 문항 본문에 끌어올 경험 요약 한 문단(part2_guide 4.22). 비어 있는 항목은 생략한다.
const ym = (d) => (d ? d.slice(0, 7).replace('-', '.') : '')

// 기간 표시(월 단위). 시작=종료(수상일 등 월 하나)면 한 번만
export function period(e) {
  if (!e.period_start && !e.period_end) return ''
  if (e.period_start && e.period_start === e.period_end) return ym(e.period_start)
  return `${ym(e.period_start)}~${ym(e.period_end)}`
}

export function experienceSummary(e) {
  const meta = [period(e), e.role].filter(Boolean).join(', ')
  const parts = [
    e.tech_stack?.length ? `사용 기술: ${e.tech_stack.join(', ')}` : '',
    e.outcome ? `성과: ${e.outcome}` : '',
    e.detail ? `상세: ${e.detail}` : '',
  ].filter(Boolean)
  return [`[${e.title}]${meta ? ` (${meta})` : ''}`, parts.join(' / ')].filter(Boolean).join(' ')
}
