import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { confirmResetPassword, resetPassword } from 'aws-amplify/auth'
import AuthCard, { authErrorMessage } from './AuthCard.jsx'
import { configureAuth } from './authConfig.js'

export default function ForgotPasswordPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState(location.state?.email ?? '')
  const [stage, setStage] = useState('request') // 'request' | 'confirm'
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [isSubmitting, setSubmitting] = useState(false)

  const request = async (e) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await configureAuth()
      await resetPassword({ username: email.trim() })
      setStage('confirm')
      setNotice('확인 코드를 보냈습니다. 메일함을 확인해 주세요.')
    } catch (err) {
      setError(authErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  const confirm = async (e) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await configureAuth()
      await confirmResetPassword({ username: email.trim(), confirmationCode: code.trim(), newPassword: password })
      navigate('/login', { replace: true, state: { email: email.trim() } })
    } catch (err) {
      setError(authErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthCard
      title="비밀번호 재설정"
      subtitle={stage === 'request' ? '가입한 이메일로 확인 코드를 보내 드립니다.' : '받은 코드와 새 비밀번호를 입력해 주세요.'}
      error={error}
      notice={notice}
      footer={<Link to="/login">로그인으로 돌아가기</Link>}
    >
      {stage === 'request' ? (
        <form className="auth-form" onSubmit={request}>
          <div className="auth-field">
            <label htmlFor="forgot-email">이메일</label>
            <input
              id="forgot-email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <button type="submit" className="auth-submit" disabled={isSubmitting}>
            {isSubmitting ? '보내는 중...' : '확인 코드 보내기'}
          </button>
        </form>
      ) : (
        <form className="auth-form" onSubmit={confirm}>
          <div className="auth-field auth-code">
            <label htmlFor="forgot-code">확인 코드</label>
            <input
              id="forgot-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              maxLength={8}
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </div>
          <div className="auth-field">
            <label htmlFor="forgot-password">새 비밀번호</label>
            <input
              id="forgot-password"
              type="password"
              autoComplete="new-password"
              required
              minLength={10}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <span className="auth-hint">10자 이상, 대문자·소문자·숫자·기호를 각각 하나 이상 포함</span>
          </div>
          <button type="submit" className="auth-submit" disabled={isSubmitting}>
            {isSubmitting ? '변경 중...' : '비밀번호 변경'}
          </button>
        </form>
      )}
    </AuthCard>
  )
}
