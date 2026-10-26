// 공통 API 클라이언트 (B1). 모든 기능 화면은 이 함수로만 백엔드를 호출한다.
// - 기준 경로는 동일 출처 /api (nginx가 app으로 프록시). 호스트 주소를 코드에 두지 않는다.
// - 액세스 토큰은 인증 모듈(D7, web/src/features/auth)이 setTokenProvider로 주입한다.

const API_BASE = '/api'

let tokenProvider = async () => null
let unauthorizedHandler = () => {}

export function setTokenProvider(fn) {
  tokenProvider = fn
}

export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = fn
}

export class ApiError extends Error {
  constructor(status, detail, { code, requestId } = {}) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.code = code ?? null // D3 에러 코드(not_found, forbidden, mfa_required ...). 문구 대신 이 값으로 분기
    this.requestId = requestId ?? null // X-Request-ID. 오류 신고 시 함께 받는다
  }
}

export async function apiFetch(path, { method = 'GET', body, headers = {}, signal } = {}) {
  if (!path.startsWith('/')) throw new Error(`path must start with "/": ${path}`)

  const token = await tokenProvider()
  const init = {
    method,
    signal,
    headers: {
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  }

  const res = await fetch(`${API_BASE}${path}`, init)
  if (res.status === 401) unauthorizedHandler()

  const isJson = res.headers.get('content-type')?.includes('application/json')
  const data = res.status === 204 ? null : isJson ? await res.json() : await res.text()
  if (!res.ok) {
    throw new ApiError(res.status, isJson ? data?.detail : data, {
      code: isJson ? data?.code : undefined,
      requestId: res.headers.get('X-Request-ID') ?? (isJson ? data?.request_id : undefined),
    })
  }
  return data
}

export const api = {
  get: (path, opts) => apiFetch(path, { ...opts, method: 'GET' }),
  post: (path, body, opts) => apiFetch(path, { ...opts, method: 'POST', body }),
  put: (path, body, opts) => apiFetch(path, { ...opts, method: 'PUT', body }),
  patch: (path, body, opts) => apiFetch(path, { ...opts, method: 'PATCH', body }),
  delete: (path, opts) => apiFetch(path, { ...opts, method: 'DELETE' }),
}
