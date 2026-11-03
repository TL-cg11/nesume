import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '../auth/useAuth.jsx'
import { adminApi, ASSIGNABLE_ROLES, errorText, ROLE_LABEL } from './api.js'
import './admin.css'

// D6 운영자: 사용자 역할 관리(일반 사용자·멘토·운영자). 처음엔 운영자·멘토 목록, 이메일로 검색하면 일반 사용자도 나온다.
// 역할이 바뀐 사용자는 기존 토큰이 무효화되어 다시 로그인해야 하고, 운영자가 되면 첫 로그인 때 TOTP 등록 화면으로 간다.
// 시스템(배치) 계정과 자기 자신은 바꿀 수 없다(서버도 막는다).
export default function AdminUsersPage() {
  const { me } = useAuth()
  const [query, setQuery] = useState('')
  const [searched, setSearched] = useState('') // 마지막으로 조회한 검색어(빈 값 = 역할 보유자 목록)
  const [items, setItems] = useState(null)
  const [draft, setDraft] = useState({}) // user_id → 고른 역할
  const [busy, setBusy] = useState(null) // 변경 중인 user_id
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)

  const load = useCallback(async (email) => {
    setError(null)
    try {
      const list = await adminApi.users(email)
      setItems(list)
      setSearched(email)
      setDraft({})
    } catch (e) {
      setError(errorText(e))
    }
  }, [])

  useEffect(() => {
    load('')
  }, [load])

  const search = (e) => {
    e.preventDefault()
    setNotice(null)
    load(query.trim())
  }

  const apply = async (u) => {
    const role = draft[u.user_id]
    if (!role || role === u.role) return
    const who = u.email ?? u.user_id
    const extra = role === 'operator' ? ' 운영자는 다음 로그인 때 인증 앱(TOTP)을 등록해야 서비스를 쓸 수 있습니다.' : ''
    if (!window.confirm(`${who}의 역할을 ${ROLE_LABEL[u.role] ?? u.role} → ${ROLE_LABEL[role]}(으)로 바꿀까요? 이 사용자는 다시 로그인해야 합니다.${extra}`)) return
    setBusy(u.user_id)
    setError(null)
    setNotice(null)
    try {
      await adminApi.changeRole(u.user_id, role)
      setNotice(`${who}: ${ROLE_LABEL[role]}(으)로 바꿨습니다.`)
      await load(searched)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <section>
      <h1>역할 관리</h1>
      <p className="muted">
        사용자에게 멘토·운영자 역할을 주거나 회수합니다. 바뀐 사용자는 다시 로그인해야 하며, 운영자는 인증 앱(TOTP)을 등록하기 전까지 아무 기능도 쓸 수 없습니다.
      </p>

      <form className="row adm-search" onSubmit={search}>
        <input
          className="grow"
          type="search"
          placeholder="이메일 앞부분 (비우면 운영자·멘토 목록)"
          value={query}
          maxLength={128}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="이메일 검색"
        />
        <button type="submit">검색</button>
      </form>

      {error && <p className="error">{error}</p>}
      {notice && <p className="success">{notice}</p>}

      {!items && !error && <p className="muted">불러오는 중...</p>}
      {items && (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <caption className="muted">{searched ? `"${searched}" 검색 결과 ${items.length}명` : `운영자·멘토 ${items.length}명`}</caption>
            <thead>
              <tr>
                <th scope="col">이메일</th>
                <th scope="col">현재 역할</th>
                <th scope="col">계정 상태</th>
                <th scope="col">역할 변경</th>
              </tr>
            </thead>
            <tbody>
              {items.map((u) => {
                const locked = u.role === 'system' || u.user_id === me?.user_id
                const chosen = draft[u.user_id] ?? u.role
                return (
                  <tr key={u.user_id}>
                    <td>{u.email ?? <span className="muted">{u.user_id}</span>}</td>
                    <td>
                      <span className={`adm-role adm-role-${u.role}`}>{ROLE_LABEL[u.role] ?? u.role}</span>
                    </td>
                    <td className="muted">
                      {u.status ?? '-'}
                      {!u.enabled && ' · 비활성'}
                    </td>
                    <td>
                      {locked ? (
                        <span className="muted">{u.role === 'system' ? '시스템 계정' : '본인'}</span>
                      ) : (
                        <div className="row adm-change">
                          <select
                            value={ASSIGNABLE_ROLES.includes(chosen) ? chosen : ''}
                            onChange={(e) => setDraft({ ...draft, [u.user_id]: e.target.value })}
                            aria-label={`${u.email ?? u.user_id} 역할`}
                          >
                            {!ASSIGNABLE_ROLES.includes(chosen) && <option value="">선택</option>}
                            {ASSIGNABLE_ROLES.map((r) => (
                              <option key={r} value={r}>
                                {ROLE_LABEL[r]}
                              </option>
                            ))}
                          </select>
                          <button onClick={() => apply(u)} disabled={busy !== null || !draft[u.user_id] || draft[u.user_id] === u.role}>
                            {busy === u.user_id ? '바꾸는 중...' : '적용'}
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
              {items.length === 0 && (
                <tr>
                  <td colSpan={4} className="muted">
                    {searched ? '일치하는 사용자가 없습니다.' : '운영자·멘토가 없습니다. 이메일로 검색해 역할을 줄 사용자를 찾으세요.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
