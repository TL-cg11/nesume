import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { signUp } from 'aws-amplify/auth'
import AuthCard, { authErrorMessage } from './AuthCard.jsx'
import { configureAuth } from './authConfig.js'

const PASSWORD_HINT = '10자 이상, 대문자·소문자·숫자·기호를 각각 하나 이상 포함'

export default function SignUpPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState(null)
  const [isSubmitting, setSubmitting] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    if (password !== confirm) {
      setError('비밀번호 확인이 일치하지 않습니다.')
      return
    }
    setSubmitting(true)
    try {
      await configureAuth()
      const username = email.trim()
      const result = await signUp({ username, password, options: { userAttributes: { email: username } } })
      if (result.isSignUpComplete) navigate('/login', { replace: true })
      else navigate('/confirm', { state: { email: username } })
    } catch (err) {
      setError(authErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthCard
      title="계정 만들기"
      subtitle="이메일로 가입하면 확인 코드를 보내 드립니다."
      error={error}
      footer={<Link to="/login">이미 계정이 있으신가요? 로그인</Link>}
    >
      <form className="auth-form" onSubmit={submit}>
        <div className="auth-field">
          <label htmlFor="signup-email">이메일</label>
          <input
            id="signup-email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="auth-field">
          <label htmlFor="signup-password">비밀번호</label>
          <input
            id="signup-password"
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <span className="auth-hint">{PASSWORD_HINT}</span>
        </div>
        <div className="auth-field">
          <label htmlFor="signup-confirm">비밀번호 확인</label>
          <input
            id="signup-confirm"
            type="password"
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </div>
        <button type="submit" className="auth-submit" disabled={isSubmitting}>
          {isSubmitting ? '가입 중...' : '가입하기'}
        </button>
      </form>
    </AuthCard>
  )
}
