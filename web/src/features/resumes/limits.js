// 문항 글자 수 규칙(10/28 결정). 서버 schemas.py의 QUESTION_TITLE_MAX·BODY_MAX와 같아야 한다
export const TITLE_MAX = 300 // 문항 제목
export const BODY_MAX = 10000 // 본문·글자수 설정 상한
export const DEFAULT_LIMIT = 1000 // 새 문항 기본 글자수
export const LIMIT_STEP = 100 // 화살표 한 번에 바뀌는 양

// 입력값 → 1~10,000 사이 정수. 비었거나 숫자가 아니면 기본값
export const clampLimit = (v, fallback = DEFAULT_LIMIT) => {
  const n = Math.round(Number(v))
  if (!v || !Number.isFinite(n) || n < 1) return fallback
  return Math.min(n, BODY_MAX)
}
