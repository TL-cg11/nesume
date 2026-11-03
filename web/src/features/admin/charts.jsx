import { useId, useState } from 'react'

// 운영자 대시보드 차트(D15). 외부 라이브러리 없이 SVG 로 그린다. 색은 dashboard.css 의 --ops-* 토큰만 쓴다.
// 규칙: 축은 하나(이중 축 없음), 2개 이상 시리즈면 범례, 막대·선은 얇게, 마우스를 올리면 툴팁.

const PAD = { top: 8, right: 8, bottom: 22, left: 36 }

export const fmtInt = (n) => (n ?? 0).toLocaleString('ko-KR')
export const fmtPct = (r, digits = 1) => `${((r ?? 0) * 100).toFixed(digits)}%`
export const fmtMs = (ms) => (ms == null ? '—' : ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`)

const timeLabel = (iso, spanHours) => {
  const d = new Date(iso)
  const hm = d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
  if (spanHours > 48) return `${d.getMonth() + 1}/${d.getDate()} ${hm}`
  return hm
}

const niceMax = (v) => {
  if (v <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(v))
  const n = v / p
  const m = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10
  return m * p
}

function Tooltip({ x, y, children }) {
  return (
    <div className="ops-tip" style={{ left: x, top: y }} role="status">
      {children}
    </div>
  )
}

function Legend({ series }) {
  if (series.length < 2) return null
  return (
    <ul className="ops-legend" aria-label="범례">
      {series.map((s) => (
        <li key={s.key}>
          <span className="ops-swatch" style={{ background: s.color }} aria-hidden="true" />
          {s.label}
        </li>
      ))}
    </ul>
  )
}

// 시간 축 차트. mode="stack": 시리즈를 쌓은 막대 / mode="line": 같은 축의 선 여러 개
// points: [{ at, values: { key: number } }], series: [{ key, label, color }]
export function TimeChart({ points, series, mode = 'stack', height = 200, spanHours = 24, unit = '건', format = fmtInt }) {
  const [hover, setHover] = useState(null)
  const id = useId()
  const width = 720
  const innerW = width - PAD.left - PAD.right
  const innerH = height - PAD.top - PAD.bottom
  const n = points.length
  const value = (p, k) => p.values[k] ?? 0
  const rawMax = Math.max(
    0,
    ...points.map((p) => (mode === 'stack' ? series.reduce((a, s) => a + value(p, s.key), 0) : Math.max(...series.map((s) => value(p, s.key))))),
  )
  const max = niceMax(rawMax)
  const x = (i) => PAD.left + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW)
  const slot = n > 0 ? innerW / n : innerW
  const y = (v) => PAD.top + innerH - (v / max) * innerH
  const ticks = [0, 0.5, 1].map((f) => f * max)
  const labelEvery = Math.max(1, Math.ceil(n / 6))

  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * width
    const i = Math.max(0, Math.min(n - 1, Math.round(((px - PAD.left) / innerW) * (n - 1))))
    setHover({ i, px: ((e.clientX - rect.left) / rect.width) * 100, py: ((e.clientY - rect.top) / rect.height) * 100 })
  }

  const empty = n === 0 || rawMax === 0
  return (
    <div className="ops-chart">
      <Legend series={series} />
      <div className="ops-chart-box" onMouseMove={empty ? undefined : onMove} onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-labelledby={`${id}-t`}>
          <title id={`${id}-t`}>{series.map((s) => s.label).join(', ')} 시간대별 추이</title>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} className="ops-gridline" />
              <text x={PAD.left - 6} y={y(t) + 4} textAnchor="end" className="ops-axis">
                {format(t)}
              </text>
            </g>
          ))}
          {points.map((p, i) =>
            i % labelEvery === 0 ? (
              <text key={p.at} x={mode === 'stack' ? PAD.left + slot * i + slot / 2 : x(i)} y={height - 6} textAnchor="middle" className="ops-axis">
                {timeLabel(p.at, spanHours)}
              </text>
            ) : null,
          )}
          {mode === 'stack' &&
            points.map((p, i) => {
              let acc = 0
              const bx = PAD.left + slot * i + slot * 0.15
              const bw = Math.max(2, slot * 0.7)
              return (
                <g key={p.at} opacity={hover && hover.i !== i ? 0.55 : 1}>
                  {series.map((s) => {
                    const v = value(p, s.key)
                    if (!v) return null
                    const y0 = y(acc + v)
                    const h = Math.max(1, y(acc) - y0 - (acc ? 2 : 0))
                    acc += v
                    return <rect key={s.key} x={bx} y={y0} width={bw} height={h} rx={acc === v ? 0 : 2} fill={s.color} />
                  })}
                </g>
              )
            })}
          {mode === 'line' &&
            series.map((s) => {
              const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(value(p, s.key)).toFixed(1)}`).join(' ')
              const area = n > 1 ? `${d} L${x(n - 1).toFixed(1)},${y(0)} L${x(0).toFixed(1)},${y(0)} Z` : ''
              return (
                <g key={s.key}>
                  {s.fill && area && <path d={area} fill={s.color} opacity="0.12" />}
                  <path d={d} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" />
                </g>
              )
            })}
          {hover && mode === 'line' && (
            <g>
              <line x1={x(hover.i)} x2={x(hover.i)} y1={PAD.top} y2={PAD.top + innerH} className="ops-crosshair" />
              {series.map((s) => (
                <circle key={s.key} cx={x(hover.i)} cy={y(value(points[hover.i], s.key))} r="4" fill={s.color} className="ops-dot" />
              ))}
            </g>
          )}
          {empty && (
            <text x={width / 2} y={height / 2} textAnchor="middle" className="ops-empty">
              이 기간에 기록이 없습니다
            </text>
          )}
        </svg>
        {hover && (
          <Tooltip x={`${Math.min(hover.px, 70)}%`} y={`${Math.min(hover.py, 60)}%`}>
            <strong>{timeLabel(points[hover.i].at, 999)}</strong>
            {series.map((s) => (
              <div key={s.key}>
                <span className="ops-swatch" style={{ background: s.color }} aria-hidden="true" />
                {s.label} <b>{format(value(points[hover.i], s.key))}</b>
                {unit}
              </div>
            ))}
          </Tooltip>
        )}
      </div>
    </div>
  )
}

// 비율 도넛: items [{ key, label, value, color }]. 가운데에 합계.
export function Donut({ items, label = '합계', size = 150 }) {
  const [hover, setHover] = useState(null)
  const total = items.reduce((a, it) => a + it.value, 0)
  const r = 54
  const c = 2 * Math.PI * r
  let offset = 0
  return (
    <div className="ops-donut">
      <svg viewBox="0 0 140 140" width={size} height={size} role="img" aria-label={`${label} ${fmtInt(total)}`}>
        <circle cx="70" cy="70" r={r} fill="none" strokeWidth="14" className="ops-donut-track" />
        {total > 0 &&
          items.map((it) => {
            const frac = it.value / total
            const dash = Math.max(0, frac * c - 2)
            const el = (
              <circle
                key={it.key}
                cx="70"
                cy="70"
                r={r}
                fill="none"
                stroke={it.color}
                strokeWidth={hover === it.key ? 18 : 14}
                strokeDasharray={`${dash} ${c - dash}`}
                strokeDashoffset={-offset}
                transform="rotate(-90 70 70)"
                onMouseEnter={() => setHover(it.key)}
                onMouseLeave={() => setHover(null)}
              />
            )
            offset += frac * c
            return el
          })}
        <text x="70" y="66" textAnchor="middle" className="ops-donut-num">
          {hover ? fmtPct(items.find((i) => i.key === hover).value / total) : fmtInt(total)}
        </text>
        <text x="70" y="84" textAnchor="middle" className="ops-donut-label">
          {hover ? items.find((i) => i.key === hover).label : label}
        </text>
      </svg>
      <ul className="ops-legend ops-legend-col">
        {items.map((it) => (
          <li key={it.key} onMouseEnter={() => setHover(it.key)} onMouseLeave={() => setHover(null)}>
            <span className="ops-swatch" style={{ background: it.color }} aria-hidden="true" />
            <span className="grow">{it.label}</span>
            <b>{fmtInt(it.value)}</b>
            <span className="muted">{total ? fmtPct(it.value / total, 0) : '—'}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// 가로 막대: items [{ key, label, value, sub?, color? }]. 값은 막대 끝에 직접 표기.
export function HBars({ items, color = 'var(--ops-c1)', format = fmtInt, onPick, picked, empty = '기록 없음' }) {
  const max = Math.max(1, ...items.map((i) => i.value))
  if (items.length === 0) return <p className="muted ops-empty-text">{empty}</p>
  return (
    <ul className="ops-hbars">
      {items.map((it) => (
        <li
          key={it.key}
          className={`${onPick ? 'pick' : ''} ${picked === it.key ? 'picked' : ''}`}
          onClick={onPick ? () => onPick(it.key) : undefined}
          title={it.sub ?? ''}
        >
          <span className="ops-hbar-label">{it.label}</span>
          <span className="ops-hbar-track">
            <span className="ops-hbar-fill" style={{ width: `${(it.value / max) * 100}%`, background: it.color ?? color }} />
            {it.sub != null && it.subValue > 0 && (
              <span className="ops-hbar-sub" style={{ width: `${(it.subValue / max) * 100}%` }} title={it.sub} />
            )}
          </span>
          <b className="ops-hbar-val">{format(it.value)}</b>
        </li>
      ))}
    </ul>
  )
}

// 100% 가로 비율 바(상태 코드 섞임 등)
export function RatioBar({ items }) {
  const total = items.reduce((a, i) => a + i.value, 0)
  return (
    <div className="ops-ratio">
      <div className="ops-ratio-bar" role="img" aria-label={items.map((i) => `${i.label} ${fmtInt(i.value)}`).join(', ')}>
        {total > 0 &&
          items.filter((i) => i.value > 0).map((i) => <span key={i.key} style={{ width: `${(i.value / total) * 100}%`, background: i.color }} title={`${i.label} ${fmtInt(i.value)}`} />)}
      </div>
      <ul className="ops-legend">
        {items.map((i) => (
          <li key={i.key}>
            <span className="ops-swatch" style={{ background: i.color }} aria-hidden="true" />
            {i.label} <b>{fmtInt(i.value)}</b>
          </li>
        ))}
      </ul>
    </div>
  )
}
