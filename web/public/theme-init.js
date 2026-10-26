// 저장된 테마를 React 마운트 전에 적용해 깜빡임(FOUC)을 막는다. 값이 없으면 OS 설정(prefers-color-scheme)을 따른다.
// 인라인 스크립트는 CSP(script-src 'self')에 막히므로 같은 출처의 외부 파일로 둔다.
try {
  var t = localStorage.getItem('nesume-theme')
  if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t)
} catch (e) {
  /* private 모드 등: 무시하고 OS 설정을 따른다 */
}
