// Amplify(Cognito) 런타임 설정 (D7).
// 설정은 빌드 시점이 아니라 nginx 가 기동 시 만들어 주는 /config.json 에서 읽는다(같은 sha 이미지를 환경 승격, D4).
// 토큰은 sessionStorage 에 둔다: 탭을 닫으면 사라지고 localStorage 보다 XSS 노출 범위가 좁다.
import { Amplify } from 'aws-amplify'
import { cognitoUserPoolsTokenProvider } from 'aws-amplify/auth/cognito'
import { sessionStorage } from 'aws-amplify/utils'

let configPromise = null
let loadedConfig = null

async function fetchConfig() {
  const res = await fetch('/config.json', { cache: 'no-store' })
  if (!res.ok) throw new Error(`config.json ${res.status}`)
  const cfg = await res.json()
  if (!cfg.userPoolId || !cfg.clientId) throw new Error('config.json 에 userPoolId/clientId 가 없습니다.')
  return cfg
}

/** 앱 시작 시 한 번. 이후 호출은 같은 Promise 를 돌려준다. */
export function configureAuth() {
  if (!configPromise) {
    configPromise = fetchConfig().then((cfg) => {
      Amplify.configure({
        Auth: {
          Cognito: {
            userPoolId: cfg.userPoolId,
            userPoolClientId: cfg.clientId,
            ...(cfg.endpoint ? { userPoolEndpoint: cfg.endpoint } : {}),
            loginWith: { email: true },
          },
        },
      })
      cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage)
      loadedConfig = cfg
      return cfg
    })
  }
  return configPromise
}

/** 로그인 플로우. 로컬(cognito-local)은 USER_PASSWORD_AUTH, 운영은 USER_SRP_AUTH. */
export function authFlowType() {
  return loadedConfig?.authFlow || 'USER_SRP_AUTH'
}
