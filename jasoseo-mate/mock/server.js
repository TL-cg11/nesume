// 개발 전용 목(mock) API — vite.config.js 에서만 연결한다.
// 운영 빌드·프론트 코드(src)와 무관. 실제 백엔드(main)가 줄 "응답 모양"만 그대로 돌려준다.
// 값은 전부 시연용이다(실제 점수·추천·강좌 아님).
//
// 다루는 경로:
//   POST /api/recommendations
//   GET  /api/roadmaps          (목록)
//   POST /api/roadmaps          (생성)
//   POST /api/roadmaps/:id/explain
//   GET  /api/roadmaps/:id
//   PATCH  /api/roadmaps/:id/items/:itemId
//   DELETE /api/roadmaps/:id/items/:itemId
// 그 외 /api/* 는 next()로 흘려보낸다(프록시가 받거나 404).

let seq = 1
const uid = () => `00000000-0000-4000-8000-${String(seq++).padStart(12, '0')}`
const now = () => new Date().toISOString()

function readBody(req) {
  return new Promise((resolve) => {
    let raw = ''
    req.on('data', (c) => (raw += c))
    req.on('end', () => {
      try {
        resolve(raw ? JSON.parse(raw) : {})
      } catch {
        resolve({})
      }
    })
  })
}

function send(res, status, data) {
  res.statusCode = status
  if (data === undefined || data === null) {
    res.end()
    return
  }
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(data))
}

// ---- 추천 공고(목) : /recommendations ----------------------------------
const DEMO_POSTINGS = [
  { title: '클라우드 보안 엔지니어', job_name: '정보보안', keys: ['aws', 'iam', 'docker', 'kubernetes', 'linux'] },
  { title: '보안 관제(SOC) 분석가', job_name: '보안관제', keys: ['siem', 'linux', '로그분석', 'network'] },
  { title: '클라우드 인프라 엔지니어', job_name: '인프라', keys: ['aws', 'terraform', 'docker', 'network'] },
  { title: 'DevSecOps 엔지니어', job_name: '플랫폼', keys: ['kubernetes', 'ci', 'docker', 'aws', 'iam'] },
]

function mockRecommend(body) {
  const held = (Array.isArray(body.held_keys) ? body.held_keys : []).map((k) => String(k).toLowerCase())
  if (held.length === 0) {
    // 개인 신호 없음 → 콜드스타트(백엔드와 동일 동작)
    return { items: [], cold_start: true, notice: '자소서·경험을 등록하면 더 정확하게 추천해 드려요.' }
  }
  const topK = Number.isInteger(body.top_k) ? body.top_k : 20
  const items = DEMO_POSTINGS.map((p) => {
    const matched = p.keys.filter((k) => held.includes(k))
    const keyword = p.keys.length ? matched.length / p.keys.length : 0
    const vector = Math.min(0.95, 0.4 + matched.length * 0.15)
    return {
      posting_id: uid(),
      score: Number((0.5 * vector + 0.5 * keyword).toFixed(3)),
      vector_score: Number(vector.toFixed(3)),
      keyword_score: Number(keyword.toFixed(3)),
      matched_keywords: matched,
      posting: { title: p.title, job_name: p.job_name },
    }
  })
    .sort((a, b) => b.score - a.score)
    .slice(0, topK)
  return { items, cold_start: false, notice: null }
}

// ---- 학습 로드맵(목) : /roadmaps ---------------------------------------
const roadmaps = new Map() // id -> RoadmapOut (세션 메모리)

// 역량 1건 → 시연용 항목 1~2개(주차 배치)
function itemsForGap(gap, baseWeek) {
  const label = gap.label || gap.key
  const out = [
    {
      id: uid(),
      origin: 'system',
      status: 'planned',
      week: baseWeek,
      position: 0,
      unverified: false,
      title: `${label} 입문 (K-MOOC)`,
      url: 'https://www.kmooc.kr/',
      hours: 3,
      source: 'kmooc',
      provider: 'K-MOOC',
      certificate: false,
    },
  ]
  if (gap.importance === 'required') {
    out.push({
      id: uid(),
      origin: 'system',
      status: 'planned',
      week: baseWeek + 1,
      position: 0,
      unverified: false,
      title: `${label} 실습 (국비 훈련)`,
      url: 'https://www.work24.go.kr/',
      hours: 4,
      source: 'work24',
      provider: '직업전문학교',
      certificate: true,
    })
  }
  return out
}

function mockCreateRoadmap(body) {
  const gaps = Array.isArray(body.gaps) ? body.gaps : []
  let week = 1
  const items = []
  for (const g of gaps) {
    const made = itemsForGap(g, week)
    items.push(...made)
    week += made.length
  }
  const roadmap = {
    id: uid(),
    job_posting_id: body.job_posting_id ?? null,
    weekly_hours: Number.isInteger(body.weekly_hours) ? body.weekly_hours : 5,
    grade: 'personal',
    explanation: null,
    created_at: now(),
    updated_at: now(),
    items,
  }
  roadmaps.set(roadmap.id, roadmap)
  return roadmap
}

// 경로 패턴
const RE_ROADMAP = /^\/api\/roadmaps\/([^/]+)$/
const RE_EXPLAIN = /^\/api\/roadmaps\/([^/]+)\/explain$/
const RE_ITEM = /^\/api\/roadmaps\/([^/]+)\/items\/([^/]+)$/

export async function handleMock(req, res) {
  const url = (req.url || '').split('?')[0]
  const method = req.method || 'GET'

  if (url === '/api/recommendations' && method === 'POST') {
    return send(res, 200, mockRecommend(await readBody(req)))
  }

  if (url === '/api/roadmaps' && method === 'GET') {
    return send(res, 200, [...roadmaps.values()])
  }
  if (url === '/api/roadmaps' && method === 'POST') {
    return send(res, 201, mockCreateRoadmap(await readBody(req)))
  }

  let m
  if ((m = url.match(RE_EXPLAIN)) && method === 'POST') {
    const r = roadmaps.get(m[1])
    if (!r) return send(res, 404, { detail: '찾을 수 없습니다' })
    r.explanation = '필수 역량을 앞 주차에 배치했습니다. 입문 강좌로 개념을 잡은 뒤 실습으로 손에 익히는 순서입니다. (시연용 설명)'
    r.updated_at = now()
    return send(res, 200, r)
  }
  if ((m = url.match(RE_ITEM)) && method === 'PATCH') {
    const r = roadmaps.get(m[1])
    if (!r) return send(res, 404, { detail: '찾을 수 없습니다' })
    const it = r.items.find((x) => x.id === m[2])
    if (!it) return send(res, 404, { detail: '찾을 수 없습니다' })
    const patch = await readBody(req)
    if (patch.status) it.status = patch.status
    if (Number.isInteger(patch.week)) it.week = patch.week
    if (Number.isInteger(patch.position)) it.position = patch.position
    return send(res, 200, it)
  }
  if ((m = url.match(RE_ITEM)) && method === 'DELETE') {
    const r = roadmaps.get(m[1])
    if (r) r.items = r.items.filter((x) => x.id !== m[2])
    return send(res, 204, null)
  }
  if ((m = url.match(RE_ROADMAP)) && method === 'GET') {
    const r = roadmaps.get(m[1])
    return r ? send(res, 200, r) : send(res, 404, { detail: '찾을 수 없습니다' })
  }

  return false // 처리 안 함 → 호출측이 next()
}

// Vite 플러그인: API_PROXY_TARGET 유무로 목 범위를 정한다.
// - 프록시 없음(Phase 1): recommendations + roadmaps 전부 목.
// - 프록시 있음(Phase 2): recommendations 만 목, 나머지는 프록시로 흘려보냄.
export function mockApiPlugin({ hasProxy }) {
  return {
    name: 'nesume-mock-api',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = (req.url || '').split('?')[0]
        if (!url.startsWith('/api/')) return next()
        // 프록시가 있으면(실백엔드 연결) 목을 전혀 쓰지 않는다 — 전부 실백엔드로.
        if (hasProxy) return next()
        const handled = await handleMock(req, res)
        if (handled === false) {
          // 프록시가 있으면 그쪽으로, 없으면(목 전용) 404 JSON — SPA HTML 이 응답으로 새는 것 방지.
          if (hasProxy) return next()
          return send(res, 404, { detail: '목에서 처리하지 않는 경로입니다(백엔드 미연결).' })
        }
      })
    },
  }
}
