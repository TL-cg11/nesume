// 로그인·MFA 화면의 ?next= 검사. 같은 출처의 경로만 허용한다(외부 주소로 보내지 않는다).
// '//evil.com' 과 '/\evil.com' 은 react-router 가 외부 주소로 해석하므로 막는다.
export function safeNext(search, fallback = '/resumes') {
  const next = new URLSearchParams(search).get('next')
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.includes('\\')) return fallback
  return next
}
