import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import AuthCard, { authErrorMessage } from './AuthCard.jsx'
import { safeNext } from './safeNext.js'
import { useAuth } from './useAuth.jsx'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [isSubmitting, setSubmitting] = useState(false)
  const next = safeNext(location.search)

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const result = await login(email.trim(), password)
      const step = result.nextStep?.signInStep
      if (result.isSignedIn || step === 'DONE') {
        navigate(next, { replace: true })
      } else if (step === 'CONFIRM_SIGN_IN_WITH_TOTP_CODE') {
        navigate(`/mfa/challenge?next=${encodeURIComponent(next)}`, { state: { email: email.trim() } })
      } else if (step === 'CONTINUE_SIGN_IN_WITH_TOTP_SETUP') {
        navigate(`/mfa/setup?next=${encodeURIComponent(next)}`, {
          state: { email: email.trim(), setupUri: result.nextStep.totpSetupDetails?.getSetupUri('nesume', email.trim())?.toString(), sharedSecret: result.nextStep.totpSetupDetails?.sharedSecret, inSignIn: true },
        })
      } else if (step === 'CONFIRM_SIGN_UP') {
        navigate('/confirm', { state: { email: email.trim() } })
      } else if (step === 'RESET_PASSWORD') {
        navigate('/forgot', { state: { email: email.trim() } })
      } else {
        setError(`지원하지 않는 로그인 단계입니다: ${step}`)
      }
    } catch (err) {
      if (err?.name === 'UserNotConfirmedException') {
        navigate('/confirm', { state: { email: email.trim() } })
        return
      }
      setError(authErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthCard
      title="로그인"
      subtitle="자소서 작성과 경험 관리를 이어서 진행하세요."
      error={error}
      footer={
        <>
          <Link to="/signup">계정 만들기</Link>
          <Link to="/forgot">비밀번호를 잊으셨나요?</Link>
        </>
      }
    >
      <form className="auth-form" onSubmit={submit}>
        <div className="auth-field">
          <label htmlFor="login-email">이메일</label>
          <input
            id="login-email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="auth-field">
          <label htmlFor="login-password">비밀번호</label>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button type="submit" className="auth-submit" disabled={isSubmitting}>
          {isSubmitting ? '로그인 중...' : '로그인'}
        </button>
      </form>
    </AuthCard>
  )
}
