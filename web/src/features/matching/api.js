// 공고 매칭 화면이 쓰는 API (A11). 공통 클라이언트만 사용한다 (프론트 가이드 5절).
//
// ★ 경험 목록은 B5 모듈을 **그대로 쓴다** (`features/experiences/api.js`).
//   같은 엔드포인트를 여기서 또 적으면 B 가 응답을 바꿀 때 두 곳을 고쳐야 한다.
import { api } from '../../app/api/client.js'

// 서버 스키마와 같아야 한다 (matching/schemas.py).
export const MAX_TEXT_LEN = 8000
export const MAX_FIELD_LEN = 8000
export const MAX_EXPERIENCES = 30
export const MAX_TERMS = 40

// 공고에서 A11 이 보는 필드. 순서가 화면 순서다.
// `rows` 는 입력칸 줄 수 — 요건 본문은 길고 직무명은 한 줄이다.
export const POSTING_FIELDS = [
  { name: 'title', label: '공고 제목', rows: 1 },
  { name: 'job_name', label: '직무명', rows: 1 },
  { name: 'job_content', label: '담당 업무·자격 요건', rows: 8 },
  { name: 'preferred', label: '우대 사항', rows: 4 },
  { name: 'certificates', label: '자격증', rows: 2 },
  { name: 'major', label: '전공', rows: 1 },
  { name: 'computer_skills', label: '전산 능력', rows: 2 },
]

// 서버가 돌려주는 필드 이름 → 화면 이름. 응답의 `fields` 를 그대로 보여주면
// 사용자에게 `job_content` 같은 컬럼 이름이 노출된다.
export const FIELD_NAMES = Object.fromEntries(POSTING_FIELDS.map((f) => [f.name, f.label]))

// 요건이 자소서·경험에 있는지 (coverage.py STATUSES).
// 순서가 서버 정렬 순서와 같다 — 할 일이 있는 것부터다.
export const STATUS_VIEW = [
  {
    id: 'in_experience_only',
    label: '지금 채울 수 있는 요건',
    hint: '경험에는 있는데 자소서에 안 쓴 것. 지어낼 필요가 없다',
    tone: 'warn',
  },
  {
    id: 'missing',
    label: '근거가 없는 요건',
    hint: '자소서에도 경험에도 없다. 문장을 만들지 않고 질문만 돌려준다',
    tone: 'danger',
  },
  {
    id: 'covered',
    label: '이미 쓴 요건',
    hint: '자소서 본문에서 찾았다',
    tone: 'ok',
  },
]

// keywords.py IMPORTANCES
export const IMPORTANCE_NAMES = {
  required: '필수',
  preferred: '우대',
  mentioned: '언급',
}

// vocab.py CATEGORIES + 사전 밖 키워드의 'other'
export const CATEGORY_NAMES = {
  language: '언어',
  framework: '프레임워크',
  data: '데이터',
  cloud: '클라우드',
  tool: '도구',
  office: '사무',
  cert: '자격증',
  domain: '도메인',
  other: '기타',
}

export const matchingApi = {
  // posting 과 posting_id 는 **하나만** 보낸다. 서버도 같은 조건으로 막는다
  // (schemas.py `_exactly_one_posting_source`) — 둘 다 보내면 어느 쪽으로
  // 분석됐는지 사용자가 알 수 없다.
  analyze: ({ posting, postingId, resumeText, experiences, useLlm = true }, signal) =>
    api.post(
      '/matching/analyze',
      {
        ...(postingId ? { posting_id: postingId } : { posting }),
        resume_text: resumeText,
        experiences,
        use_llm: useLlm,
      },
      { signal },
    ),
}
