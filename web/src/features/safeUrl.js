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

// 원문 링크가 없는 공고(서울시 공공데이터 — API에 주소·고유번호가 없음)는 고용24 채용정보 **검색 결과**로 보낸다.
// 원문이 아니라 검색이므로 화면 문구도 "검색"으로 둔다. 주소·경로는 고정, 회사명은 검색어로만 들어간다(인코딩).
// 회사명만 쓴다(C8.md 11-02 결정: 회사+제목 조합은 0건이 나온 사례가 있음).
const WORK24_SEARCH = 'https://www.work24.go.kr/wk/a/b/1200/retriveDtlEmpSrchList.do'
const CORP_MARK = /\(주\)|㈜|주식회사|\(유\)|유한회사|\(재\)|재단법인|\(사\)|사단법인/g

export function work24SearchUrl(companyName) {
  const q = (companyName || '').replace(CORP_MARK, ' ').replace(/\s+/g, ' ').trim().slice(0, 30) // 고용24 검색창 최대 30자
  return q ? `${WORK24_SEARCH}?srcKeyword=${encodeURIComponent(q)}` : null
}
