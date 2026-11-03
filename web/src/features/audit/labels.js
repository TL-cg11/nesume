// AI 사용 기록 판정 상세(11/3, part2_guide 4.74): 규칙 ID·단계·가린 자리를 운영자가 읽을 수 있는 말로.
// 규칙 뜻은 차단 정책 표(docs/policy/block-policy.md)와 A1·A3·A5·A12·C6·C13 규칙을 따른다. 원래 값은 보여 주지 않는다

export const STAGE = {
  classifier: '입력 검사',
  retriever: '검색 결과 검사',
  output_guard: '출력 검사',
}

// 단계별로 '차단'이 무엇을 뜻하는지
export const BLOCK_WHEN = {
  classifier: 'AI를 부르기 전에 질문을 막았습니다.',
  retriever: '검색 결과에 나올 수 없는 자료가 섞여 AI를 부르지 않았습니다.',
  output_guard: 'AI가 만든 응답을 사용자에게 보내기 전에 막았습니다. 막힌 응답은 기록하지 않습니다.',
}

export const MASK_WHEN = {
  classifier: '질문 속 개인정보를 가린 채로 처리했습니다.',
  retriever: '검색 결과를 가린 채로 처리했습니다.',
  output_guard: '응답 속 개인정보를 가려서 돌려주었습니다.',
}

const RULES = {
  PII_RRN: '주민등록번호 입력(저장·처리 거부)',
  PII_ACCOUNT: '계좌번호 입력(저장·처리 거부)',
  PII_PHONE: '전화번호',
  PII_EMAIL: '이메일',
  PII_PERSON: '사람 이름',
  SENS_IDNUM: '민감한 식별번호(여권·운전면허 등) 요구·포함',
  SENS_OTHER_PERSON: '다른 사람의 개인정보 요구',
  INJ_SYSPROMPT: '시스템 지침·초기 지시 노출 요구',
  INJ_DIRECT: '지시 무시·역할 탈취 시도',
  EXF_BULK: '전체 사용자·문서 대량 유출 요구',
  AUTHZ_OTHER_RESUME: '다른 사람의 자기소개서 요구',
  AUTHZ_OPERATOR_ONLY: '운영자 전용 자료 요구',
  AUTHZ_TEMPLATE: '내부 템플릿 요구',
  AUTHZ_FILTER_BYPASS: '검색 결과에 받을 수 없는 자료가 섞임(권한 필터 우회)',
  MT_SLICING: '여러 번에 나눠 보호 정보를 조금씩 요구',
  MT_CONTINUATION: '직전에 제한된 요청을 이어서 요구',
  MT_SPLIT_INJECTION: '여러 번에 나눠 넣은 지시 탈취 시도',
  MT_ESCALATION: '민감·탈취 시도 누적(표시만)',
  LEAK_CANARY: '미끼(카나리) 문서 노출',
  LEAK_OTHER_USER: '다른 사용자 문서 노출',
  OUT_UNKNOWN_TOKEN: '알 수 없는 개인정보 표시',
  ERR_PIPELINE: '처리 중 오류',
}

export function ruleText(id) {
  if (RULES[id]) return RULES[id]
  if (id.startsWith('LEAK_SECRET')) return '비밀번호·키 등 자격증명 노출'
  if (id.startsWith('AUTHZ_')) return '권한 밖 자료 요구'
  if (id.startsWith('PII_')) return '개인정보'
  return '기타 규칙'
}

// 가린 자리: 토큰([[PHONE_1]])과 별표(***-****-****, ***@***)
const KIND = { PERSON: '이름', ORG: '기관명', SCHOOL: '학교명', PHONE: '전화번호', EMAIL: '이메일', ADDRESS: '주소' }
const MASKED = /\[\[([A-Z]+)_\d+\]\]|\*{3,}(?:[-@.]\*{2,})*/g

function maskedKind(m) {
  if (m.startsWith('[[')) return KIND[m.slice(2).split('_')[0]] ?? '비공개 정보'
  if (m.includes('@')) return '이메일'
  if (m.includes('-')) return '번호'
  return '비공개 정보'
}

// 글을 [{text} | {masked, kind}] 조각으로 나눈다
export function splitMasked(text) {
  const out = []
  let last = 0
  for (const m of text.matchAll(MASKED)) {
    if (m.index > last) out.push({ text: text.slice(last, m.index) })
    out.push({ masked: m[0], kind: maskedKind(m[0]) })
    last = m.index + m[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last) })
  return out
}

// 가린 항목 종류별 개수 { 전화번호: 2, 이메일: 1 }
export function maskedCounts(...texts) {
  const counts = {}
  for (const t of texts) {
    for (const part of splitMasked(t ?? '')) if (part.masked) counts[part.kind] = (counts[part.kind] ?? 0) + 1
  }
  return counts
}

// 기능 이름(D15 대시보드 FEATURE와 같은 값. 11/3 대화 묶어 보기, part2_guide 4.77)
const FEATURE = {
  interview: '면접 연습',
  'rewrite.generate': '자소서 리라이팅',
  'writing.proofread': '글 다듬기(맞춤법)',
  'writing.star': 'STAR 점검',
  'writing.star_complete': 'STAR 보완',
  'github.intro': 'GitHub 소개',
  'matching.analyze': '공고 매칭',
  'style.adjust': '문체 조정',
  'share.view': '멘토 공유 열람',
}
export const featureText = (f) => FEATURE[f] ?? f

// 대화 이름: 기능 + 세션 ID 앞 8자(면접은 'interview-<면접 ID>' → 면접 ID 앞 8자). 세션 없는 단발 요청은 null
export const conversationName = (log) => {
  const id = (log.session_id ?? '').trim()
  if (!id) return null
  const short = id.replace(/^[a-z_]+-(?=[0-9a-f]{8})/i, '').slice(0, 8)
  return `${featureText(log.feature)} · ${short}`
}
