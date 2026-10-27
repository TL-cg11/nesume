import { useCallback, useEffect, useState } from 'react'
import { errorText, placeholders, templatesApi } from './api.js'
import './templates.css'

// B9 운영자: 프롬프트 템플릿 목록·버전 이력·새 템플릿/새 버전·활성 전환(spec 3.6, part2_guide 4.52)
// 수정은 새 버전(덮어쓰기 없음). 변수는 본문의 {{변수}}에서 자동으로 뽑는다. 활성 전환은 MFA 세션 필요.
const emptyNew = { name: '', purpose: '', body: '' }

function VariableChips({ body }) {
  const vars = placeholders(body)
  return (
    <p className="muted">
      변수: {vars.length ? vars.map((v) => <code key={v} className="tpl-var">{`{{${v}}}`}</code>) : '없음'}
    </p>
  )
}

export default function TemplatesPage() {
  const [items, setItems] = useState(null)
  const [selected, setSelected] = useState(null) // 이름
  const [versions, setVersions] = useState([])
  const [draft, setDraft] = useState('') // 새 버전 본문
  const [creating, setCreating] = useState(null) // 새 템플릿 폼
  const [error, setError] = useState(null)

  const load = useCallback(() => templatesApi.list().then(setItems), [])
  const loadVersions = useCallback(async (name) => {
    const list = await templatesApi.versions(name)
    setVersions(list)
    setDraft(list[0]?.body ?? '')
  }, [])

  useEffect(() => {
    load().catch((e) => setError(errorText(e)))
  }, [load])

  const run = async (fn) => {
    try {
      await fn()
      setError(null)
      return true
    } catch (e) {
      setError(errorText(e))
      return false
    }
  }

  const open = (name) => run(async () => {
    setSelected(name)
    await loadVersions(name)
  })

  const create = () => run(async () => {
    const t = await templatesApi.create({ ...creating, variables: placeholders(creating.body) })
    setCreating(null)
    await load()
    await open(t.name)
  })

  const saveVersion = () => run(async () => {
    await templatesApi.newVersion(selected, { body: draft, variables: placeholders(draft) })
    await Promise.all([load(), loadVersions(selected)])
  })

  const activate = (v) => {
    if (!window.confirm(`${selected} v${v.version}을(를) 활성 버전으로 바꿀까요? 작성 AI가 바로 이 버전을 씁니다.`)) return
    run(async () => {
      await templatesApi.activate(v.id)
      await Promise.all([load(), loadVersions(selected)])
    })
  }

  if (error && !items) return <p className="error">{error}</p>
  if (!items) return <p className="muted">불러오는 중...</p>

  return (
    <section>
      <div className="row">
        <h1 className="grow">프롬프트 템플릿</h1>
        <button onClick={() => setCreating(emptyNew)} disabled={!!creating}>
          새 템플릿
        </button>
      </div>
      <p className="muted">운영자 전용 내부 문서입니다. 수정하면 새 버전이 만들어지고, 활성 전환은 MFA 로그인 상태에서만 됩니다.</p>
      {error && <p className="error">{error}</p>}

      {creating && (
        <div className="card stack tpl-editor">
          <div className="row">
            <input
              placeholder="이름 (예: rewrite-default)"
              value={creating.name}
              maxLength={100}
              onChange={(e) => setCreating({ ...creating, name: e.target.value.toLowerCase() })}
              aria-label="템플릿 이름"
            />
            <input
              placeholder="용도 (예: rewrite)"
              value={creating.purpose}
              maxLength={50}
              onChange={(e) => setCreating({ ...creating, purpose: e.target.value })}
              aria-label="용도"
            />
          </div>
          <textarea
            rows={8}
            placeholder="본문. 변수는 {{변수}}"
            value={creating.body}
            maxLength={20000}
            onChange={(e) => setCreating({ ...creating, body: e.target.value })}
            aria-label="본문"
          />
          <VariableChips body={creating.body} />
          <div className="row">
            <button onClick={create} disabled={!creating.name || !creating.purpose.trim() || !creating.body}>
              만들기(1버전)
            </button>
            <button className="secondary" onClick={() => setCreating(null)}>
              취소
            </button>
          </div>
        </div>
      )}

      <div className="tpl-grid">
        <ul className="list">
          {items.map((t) => (
            <li key={t.name} className={t.name === selected ? 'tpl-selected' : ''}>
              <button className="link" onClick={() => open(t.name)}>
                {t.name}
              </button>
              <span className="muted">
                {' '}
                {t.purpose} · 최신 v{t.latest_version} · {t.active_version ? `활성 v${t.active_version}` : '활성 없음'}
              </span>
            </li>
          ))}
          {items.length === 0 && <li className="muted">템플릿이 없습니다.</li>}
        </ul>

        {selected && (
          <div className="stack tpl-editor">
            <h2>{selected}</h2>
            <textarea rows={10} value={draft} maxLength={20000} onChange={(e) => setDraft(e.target.value)} aria-label="새 버전 본문" />
            <VariableChips body={draft} />
            <div className="row">
              <button onClick={saveVersion} disabled={!draft || draft === versions[0]?.body}>
                새 버전으로 저장
              </button>
            </div>
            <h3>버전 이력</h3>
            <ul className="timeline">
              {versions.map((v) => (
                <li key={v.id}>
                  <strong>v{v.version}</strong>
                  {v.is_active && <span className="tpl-active">활성</span>}
                  <span className="muted grow">
                    {new Date(v.created_at).toLocaleString()} · 작성 {v.created_by.slice(0, 8)}…
                  </span>
                  <button className="secondary" onClick={() => setDraft(v.body)}>
                    이 본문 불러오기
                  </button>
                  {!v.is_active && <button onClick={() => activate(v)}>활성 전환</button>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}
