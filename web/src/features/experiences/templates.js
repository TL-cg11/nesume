// 경험 유형별 작성 템플릿(10/28 결정). 저장 칸은 모든 유형이 같고(spec 3.5), 칸 이름·예시·표시 여부만 다르다.
// period: 'range' = 시작~종료 월, 'single' = 월 하나(수상일, 시작·종료에 같은 값 저장)
export const TYPES = ['프로젝트', '활동', '수상', 'GitHub', '기타']

const BASE = {
  title: { label: '제목', placeholder: '' },
  period: 'range',
  role: { label: '역할', placeholder: '' },
  tech: true,
  outcome: { label: '성과', placeholder: '' },
  detail: { label: '상세 서술', placeholder: '' },
}

export const TEMPLATES = {
  프로젝트: {
    ...BASE,
    title: { label: '프로젝트명', placeholder: '예: 실시간 투표 서비스' },
    role: { label: '맡은 역할', placeholder: '예: 백엔드 API 설계, 캐시 계층 도입' },
    outcome: { label: '성과', placeholder: '예: 응답 지연 p95 1.2s → 180ms (가능하면 수치로)' },
    detail: { label: '상세 서술', placeholder: '배경·문제 → 해결 과정(내가 한 일) → 배운 점' },
  },
  활동: {
    ...BASE,
    title: { label: '활동명', placeholder: '예: OO 동아리, OO 서포터즈, 봉사활동' },
    role: { label: '역할(직책)', placeholder: '예: 기획팀장, 운영진' },
    tech: false,
    outcome: { label: '성과', placeholder: '예: 행사 참여자 120명 모집' },
    detail: { label: '상세 서술', placeholder: '활동 내용 → 내가 한 일 → 느낀 점' },
  },
  수상: {
    ...BASE,
    title: { label: '수상명', placeholder: '예: OO 해커톤 최우수상' },
    period: 'single',
    role: { label: '수여 기관', placeholder: '예: OO대학교, OO재단' },
    tech: false,
    outcome: { label: '수상 등급·의미', placeholder: '예: 32팀 중 1위' },
    detail: { label: '상세 서술', placeholder: '수상 대상(무엇으로 받았는지) → 내 기여' },
  },
  GitHub: {
    ...BASE,
    title: { label: '프로젝트명', placeholder: '초안 생성 시 저장소 이름으로 채워집니다' },
    role: { label: '맡은 역할', placeholder: '예: 백엔드 API 설계' },
    outcome: { label: '성과', placeholder: '예: 응답시간 40% 단축 (가능하면 수치로)' },
    detail: { label: '상세 서술', placeholder: '배경 → 역할 → 기술 (초안 생성 시 자동으로 채워집니다)' },
  },
  기타: BASE,
}

// 목록에 없는 예전 자유 입력 유형은 '기타'로 본다(저장하면 기타로 바뀜, 10/28 결정)
export const normalizeType = (t) => (TYPES.includes(t) ? t : '기타')

// 날짜(YYYY-MM-DD) ↔ 월 입력칸(YYYY-MM). 저장은 그 달 1일
export const toMonth = (d) => (d ? d.slice(0, 7) : '')
export const fromMonth = (m) => (m ? `${m}-01` : null)
