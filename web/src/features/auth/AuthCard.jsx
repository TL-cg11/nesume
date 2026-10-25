// 인증 화면 공통 틀: 가운데 카드 + 제목 + 설명 + 상태 메시지.
import './auth.css'

export default function AuthCard({ title, subtitle, error, notice, children, footer }) {
  return (
    <section className="auth-wrap">
      <div className="auth-card card">
        <p className="auth-eyebrow">nesume</p>
        <h1 className="auth-title">{title}</h1>
        {subtitle && <p className="auth-subtitle">{subtitle}</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {notice && <p className="notice">{notice}</p>}
        {children}
        {footer && <div className="auth-footer">{footer}</div>}
      </div>
    </section>
  )
}

/** Amplify/Cognito 오류를 사용자 문구로. 존재 여부를 드러내지 않는다(PreventUserExistenceErrors 와 같은 원칙). */
export function authErrorMessage(e) {
  const name = e?.name || ''
  const message = e?.message || ''
  if (e?.detail) return e.detail // 백엔드 D3 형식
  switch (name) {
    case 'NotAuthorizedException':
    case 'UserNotFoundException':
      return '이메일 또는 비밀번호가 올바르지 않습니다.'
    case 'UserNotConfirmedException':
      return '이메일 인증이 끝나지 않았습니다. 받은 확인 코드를 입력해 주세요.'
    case 'CodeMismatchException':
      return '확인 코드가 올바르지 않습니다.'
    case 'ExpiredCodeException':
      return '확인 코드가 만료되었습니다. 다시 요청해 주세요.'
    case 'InvalidPasswordException':
      return '비밀번호는 10자 이상, 대문자·소문자·숫자·기호를 포함해야 합니다.'
    case 'UsernameExistsException':
      return '가입할 수 없는 이메일입니다. 이미 계정이 있다면 로그인해 주세요.'
    case 'LimitExceededException':
    case 'TooManyRequestsException':
      return '요청이 많습니다. 잠시 후 다시 시도해 주세요.'
    case 'EnableSoftwareTokenMFAException':
      return '인증 앱 코드가 올바르지 않습니다. 다시 입력해 주세요.'
    case 'NetworkError':
      return '인증 서버에 연결할 수 없습니다.'
    default:
      return message || '요청을 처리하지 못했습니다.'
  }
}
