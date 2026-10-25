import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { confirmSignUp, resendSignUpCode } from 'aws-amplify/auth'
import AuthCard, { authErrorMessage } from './AuthCard.jsx'
import { configureAuth } from './authConfig.js'

export default function ConfirmSignUpPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState(location.state?.email ?? '')
  const [code, setCode] = useState('')
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [isSubmitting, setSubmitting] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await configureAuth()
      await confirmSignUp({ username: email.trim(), confirmationCode: code.trim() })
      navigate('/login', { replace: true, state: { email: email.trim() } })
    } catch (err) {
      setError(authErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  const resend = async () => {
    setError(null)
    try {
      await configureAuth()
      await resendSignUpCode({ username: email.trim() })
      setNotice('확인 코드를 다시 보냈습니다. 메일함을 확인해 주세요.')
    } catch (err) {
      setError(authErrorMessage(err))
    }
  }

  return (
    <AuthCard
      title="이메일 확인"
      subtitle="메일로 받은 확인 코드를 입력해 주세요. 로컬 환경에서는 docker compose logs cognito 에 출력됩니다."
      error={error}
      notice={notice}
      footer={<Link to="/login">로그인으로 돌아가기</Link>}
    >
      <form className="auth-form" onSubmit={submit}>
        <div className="auth-field">
          <label htmlFor="confirm-email">이메일</label>
          <input
            id="confirm-email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="auth-field auth-code">
          <label htmlFor="confirm-code">확인 코드</label>
          <input
            id="confirm-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            required
            maxLength={8}
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </div>
        <button type="submit" className="auth-submit" disabled={isSubmitting}>
          {isSubmitting ? '확인 중...' : '확인'}
        </button>
        <button type="button" className="secondary" onClick={resend} disabled={!email}>
          코드 다시 보내기
        </button>
      </form>
    </AuthCard>
  )
}
