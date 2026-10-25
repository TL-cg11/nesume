// 로그인 중 TOTP 코드 입력 단계 (signIn nextStep = CONFIRM_SIGN_IN_WITH_TOTP_CODE).
import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { confirmSignIn } from 'aws-amplify/auth'
import AuthCard, { authErrorMessage } from './AuthCard.jsx'
import { useAuth } from './useAuth.jsx'

export default function MfaChallengePage() {
  const { completeSignIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [code, setCode] = useState('')
  const [error, setError] = useState(null)
  const [isSubmitting, setSubmitting] = useState(false)
  const next = new URLSearchParams(location.search).get('next') || '/resumes'

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const result = await confirmSignIn({ challengeResponse: code.trim() })
      if (result.isSignedIn) {
        await completeSignIn(location.state?.email)
        navigate(next.startsWith('/') ? next : '/resumes', { replace: true })
      } else {
        setError(`추가 단계가 필요합니다: ${result.nextStep?.signInStep}`)
      }
    } catch (err) {
      setError(authErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthCard
      title="인증 코드 입력"
      subtitle="인증 앱(Google Authenticator 등)에 표시된 6자리 코드를 입력해 주세요."
      error={error}
      footer={<Link to="/login">처음부터 다시 로그인</Link>}
    >
      <form className="auth-form" onSubmit={submit}>
        <div className="auth-field auth-code">
          <label htmlFor="mfa-code">6자리 코드</label>
          <input
            id="mfa-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            maxLength={6}
            required
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </div>
        <button type="submit" className="auth-submit" disabled={isSubmitting || code.length !== 6}>
          {isSubmitting ? '확인 중...' : '확인'}
        </button>
      </form>
    </AuthCard>
  )
}
