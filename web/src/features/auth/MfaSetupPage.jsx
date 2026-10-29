// TOTP 등록 (운영자 필수, 일반 사용자 선택).
// - TOTP 미등록 운영자는 로그인 직후 이 화면으로 오고(useAuth 가드), 등록 전에는 다른 화면으로 갈 수 없다.
//   "나중에 하기" 대신 로그아웃만 보인다.
// - 로그인 상태: setUpTOTP → QR → verifyTOTPSetup → updateMFAPreference(totp PREFERRED)
// - 로그인 도중(signIn nextStep = CONTINUE_SIGN_IN_WITH_TOTP_SETUP): LoginPage 가 setupUri 를 state 로 넘기고,
//   코드 확인은 confirmSignIn 으로 한다.
import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { confirmSignIn, setUpTOTP, updateMFAPreference, verifyTOTPSetup } from 'aws-amplify/auth'
import QRCode from 'qrcode'
import AuthCard, { authErrorMessage } from './AuthCard.jsx'
import { safeNext } from './safeNext.js'
import { useAuth } from './useAuth.jsx'

export default function MfaSetupPage() {
  const { status, email, mfaRequired, completeSignIn, logout, refreshMe } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const inSignIn = Boolean(location.state?.inSignIn)
  const [setupUri, setSetupUri] = useState(location.state?.setupUri ?? null)
  const [secret, setSecret] = useState(location.state?.sharedSecret ?? null)
  const [qr, setQr] = useState(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState(null)
  const [isSubmitting, setSubmitting] = useState(false)
  const next = safeNext(location.search)

  // 로그인 상태에서 들어온 경우 새 비밀키 발급
  useEffect(() => {
    if (inSignIn || setupUri) return
    if (status !== 'authed') return
    let cancelled = false
    ;(async () => {
      try {
        const details = await setUpTOTP()
        if (cancelled) return
        setSecret(details.sharedSecret)
        setSetupUri(details.getSetupUri('nesume', email ?? undefined).toString())
      } catch (err) {
        if (!cancelled) setError(authErrorMessage(err))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [inSignIn, setupUri, status, email])

  useEffect(() => {
    if (!setupUri) return
    QRCode.toDataURL(setupUri, { width: 180, margin: 1 })
      .then(setQr)
      .catch(() => setQr(null))
  }, [setupUri])

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      if (inSignIn) {
        const result = await confirmSignIn({ challengeResponse: code.trim() })
        if (!result.isSignedIn) throw new Error(`추가 단계가 필요합니다: ${result.nextStep?.signInStep}`)
        await completeSignIn(location.state?.email)
      } else {
        await verifyTOTPSetup({ code: code.trim() })
        await updateMFAPreference({ totp: 'PREFERRED' })
        const data = await refreshMe()
        if (data?.mfa_required) throw new Error('등록이 아직 확인되지 않았습니다. 잠시 후 다시 시도해 주세요.')
      }
      navigate(next, { replace: true })
    } catch (err) {
      setError(authErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (!inSignIn && status === 'anon') {
    return (
      <AuthCard title="인증 앱 등록" error="로그인 후 등록할 수 있습니다." footer={<Link to="/login">로그인</Link>} />
    )
  }

  return (
    <AuthCard
      title="인증 앱 등록"
      subtitle={
        mfaRequired
          ? '운영자 계정은 인증 앱(TOTP)을 등록해야 서비스를 이용할 수 있습니다. 인증 앱으로 QR 을 스캔하고 표시된 코드를 입력해 주세요.'
          : '운영자 기능은 TOTP 등록 후 사용할 수 있습니다. 인증 앱으로 QR 을 스캔하고 표시된 코드를 입력해 주세요.'
      }
      error={error}
      footer={
        mfaRequired ? (
          <button type="button" className="link" onClick={logout}>
            로그아웃
          </button>
        ) : (
          <Link to={next}>나중에 하기</Link>
        )
      }
    >
      <div className="auth-qr">
        {qr ? <img src={qr} alt="TOTP 등록 QR 코드" /> : <span className="muted">QR 코드를 준비하는 중...</span>}
        {secret && (
          <>
            <span className="auth-hint">QR 을 스캔할 수 없으면 키를 직접 입력하세요.</span>
            <code className="auth-secret">{secret}</code>
          </>
        )}
      </div>
      <form className="auth-form" onSubmit={submit}>
        <div className="auth-field auth-code">
          <label htmlFor="mfa-setup-code">인증 앱에 표시된 6자리 코드</label>
          <input
            id="mfa-setup-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            maxLength={6}
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </div>
        <button type="submit" className="auth-submit" disabled={isSubmitting || code.length !== 6 || !setupUri}>
          {isSubmitting ? '확인 중...' : '등록 완료'}
        </button>
      </form>
    </AuthCard>
  )
}
