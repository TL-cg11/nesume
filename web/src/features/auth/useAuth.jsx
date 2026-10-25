// 인증 상태 Provider + 훅 (D7).
// - 시작 시 /config.json → Amplify 설정 → 세션 토큰이 있으면 client.js 에 토큰 공급자를 등록하고 /auth/me 를 부른다.
// - 401 이 오면(client.js setUnauthorizedHandler) 세션을 지우고 /login 으로 보낸다.
// - 화면은 useAuth() 로 { status, me, email, login, logout, refreshMe } 를 쓴다. 토큰 자체는 노출하지 않는다.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { fetchAuthSession, getCurrentUser, signIn, signOut } from 'aws-amplify/auth'
import { setTokenProvider, setUnauthorizedHandler } from '../../app/api/client.js'
import { authApi } from './api.js'
import { authFlowType, configureAuth } from './authConfig.js'

const AuthContext = createContext(null)

const AUTH_PATHS = ['/login', '/signup', '/confirm', '/forgot', '/mfa/challenge', '/mfa/setup']

async function currentAccessToken() {
  try {
    const session = await fetchAuthSession()
    return session.tokens?.accessToken?.toString() ?? null
  } catch {
    return null
  }
}

export function AuthProvider({ children }) {
  const navigate = useNavigate()
  const location = useLocation()
  // status: 'loading' | 'anon' | 'authed' | 'error'
  const [status, setStatus] = useState('loading')
  const [me, setMe] = useState(null) // { user_id, role, is_test, username }
  const [email, setEmail] = useState(null)
  const [mfaRequired, setMfaRequired] = useState(false)
  const [configError, setConfigError] = useState(null)
  const redirecting = useRef(false)
  const statusRef = useRef('loading')
  statusRef.current = status

  // 첫 렌더에서 바로 토큰 공급자를 등록한다. 자식 화면이 마운트 직후 API 를 불러도(새로고침)
  // 설정·세션 복원이 끝날 때까지 기다렸다가 토큰을 붙이므로 불필요한 401 이 나지 않는다.
  useState(() => {
    setTokenProvider(async () => {
      try {
        await configureAuth()
      } catch {
        return null
      }
      return currentAccessToken()
    })
    return true
  })

  const loadMe = useCallback(async () => {
    try {
      const data = await authApi.me()
      setMe(data)
      setMfaRequired(false)
      return data
    } catch (e) {
      // 운영자인데 TOTP 미등록이면 /auth/me 는 200 이지만 보호 API 가 403 mfa_required. 여기서는 403 만 표시용으로 기록.
      if (e.status === 403 && e.code === 'mfa_required') setMfaRequired(true)
      throw e
    }
  }, [])

  const clearSession = useCallback(async () => {
    try {
      await signOut()
    } catch {
      /* 이미 로그아웃된 경우 */
    }
    setMe(null)
    setEmail(null)
    setMfaRequired(false)
    setStatus('anon')
  }, [])

  // 앱 시작: 설정 → 세션 복원
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        await configureAuth()
      } catch (e) {
        if (!cancelled) {
          setConfigError(e)
          setStatus('error')
        }
        return
      }
      const token = await currentAccessToken()
      if (cancelled) return
      if (!token) {
        setStatus('anon')
        return
      }
      try {
        const user = await getCurrentUser()
        setEmail(user.signInDetails?.loginId ?? user.username ?? null)
        await loadMe()
        if (!cancelled) setStatus('authed')
      } catch {
        if (!cancelled) await clearSession()
      }
    })()
    return () => {
      cancelled = true
    }
  }, [loadMe, clearSession])

  // 401 → 세션 정리 후 로그인 화면. 인증 화면에서 난 401 은 무시(중복 이동 방지).
  useEffect(() => {
    setUnauthorizedHandler(() => {
      // 세션 복원 중(loading)이거나 이미 비로그인 상태면 이동만 하고 세션은 건드리지 않는다.
      if (redirecting.current || AUTH_PATHS.includes(location.pathname)) return
      if (statusRef.current === 'loading') return
      redirecting.current = true
      clearSession().finally(() => {
        const next = encodeURIComponent(location.pathname + location.search)
        navigate(`/login?next=${next}`, { replace: true })
        redirecting.current = false
      })
    })
    return () => setUnauthorizedHandler(() => {})
  }, [clearSession, navigate, location.pathname, location.search])

  /** MFA 입력 등 추가 단계가 끝난 뒤 호출. 토큰 공급자 등록 + /auth/me. */
  const completeSignIn = useCallback(
    async (username) => {
      setEmail(username ?? null)
      await loadMe()
      setStatus('authed')
    },
    [loadMe],
  )

  /** 로그인. 반환값 { nextStep } 은 Amplify signIn 결과 그대로(CONFIRM_SIGN_IN_WITH_TOTP_CODE 등). */
  const login = useCallback(
    async (username, password) => {
      await configureAuth()
      const result = await signIn({ username, password, options: { authFlowType: authFlowType() } })
      if (result.isSignedIn) await completeSignIn(username)
      return result
    },
    [completeSignIn],
  )

  const logout = useCallback(async () => {
    await clearSession()
    navigate('/login', { replace: true })
  }, [clearSession, navigate])

  const value = useMemo(
    () => ({ status, me, email, mfaRequired, configError, login, completeSignIn, logout, refreshMe: loadMe }),
    [status, me, email, mfaRequired, configError, login, completeSignIn, logout, loadMe],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 는 AuthProvider 안에서만 쓸 수 있습니다.')
  return ctx
}
