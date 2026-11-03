// 경험 기간 표시. 끌어온 경험을 본문에 넣던 요약(4.22)은 10/28 없앰 — 연결만 한다(4.65)
const ym = (d) => (d ? d.slice(0, 7).replace('-', '.') : '')

// 기간 표시(월 단위). 시작=종료(수상일 등 월 하나)면 한 번만
export function period(e) {
  if (!e.period_start && !e.period_end) return ''
  if (e.period_start && e.period_start === e.period_end) return ym(e.period_start)
  return `${ym(e.period_start)}~${ym(e.period_end)}`
}
