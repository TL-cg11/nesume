// 공고 원문 링크는 기업별 외부 도메인이라 서버가 http/https만 저장한다. 화면에서도 한 번 더 확인(심층 방어).
// 서버는 링크를 가져오지 않는다(SSRF) — 사용자가 새 창으로 직접 연다.
export function safeUrl(url) {
  try {
    const u = new URL(url)
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null
  } catch {
    return null
  }
}
