// A14 — 내 말투 프로필 패널.
//
// ★ 본인만 볼 수 있다. 멘토·운영자도 조회할 수 없다 (tasks.md A14).
// ★ 프롬프트에 들어가는 문단을 그대로 보여준다 — 무엇이 모델에 가는지 사용자가 알아야 한다.
// ★ 지울 수 있어야 한다. 사용자가 만들라고 한 적 없는 파생 데이터다.

import { useCallback, useEffect, useState } from 'react'
import { MIN_PROFILE_CHARS, profileApi } from './api.js'

export default function ProfilePanel({ text, run, isBusy }) {
  const [profile, setProfile] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [note, setNote] = useState(null)

  const load = useCallback(async () => {
    const body = await run((signal) => profileApi.read(signal), { quiet404: true })
    setProfile(body)
    setLoaded(true)
  }, [run])

  useEffect(() => {
    load()
  }, [load])

  const build = async () => {
    setNote(null)
    const body = await run((signal) => profileApi.build(text, signal))
    if (!body) return
    setProfile(body)
    setNote('지금 글로 말투를 다시 뽑았습니다.')
  }

  const remove = async () => {
    setNote(null)
    const ok = await run(async (signal) => {
      await profileApi.remove(signal)
      return true
    })
    if (!ok) return
    setProfile(null)
    setNote('말투 프로필을 지웠습니다.')
  }

  const short = text.length < MIN_PROFILE_CHARS

  return (
    <div className="stack">
      <p className="muted">
        평소 문체를 뽑아 두면 AI가 다시 쓸 때 그 문체에 맞춥니다.
        <strong> 본인만 볼 수 있습니다</strong> — 멘토·운영자도 조회할 수 없습니다.
      </p>

      {note && <p className="success">{note}</p>}
      {isBusy && <p className="muted">불러오는 중...</p>}

      {!isBusy && loaded && !profile && (
        <p className="muted">
          아직 말투 프로필이 없습니다. 쓴 글 {MIN_PROFILE_CHARS.toLocaleString()}자 이상으로 만들 수 있습니다.
        </p>
      )}

      {!isBusy && profile && (
        <>
          <div className="card wr-metric">
            <div className="row">
              <strong className="grow">내 말투</strong>
              {profile.thin && <span className="wr-badge check">표본 적음</span>}
            </div>
            <ul className="list">
              <li>문장 평균 {profile.avg_sentence_len}자 · 문단당 문장 {profile.paragraph_avg_sentences}개</li>
              {profile.endings.length > 0 && <li>자주 쓰는 문장 끝: {profile.endings.join(' · ')}</li>}
              {profile.connectives.length > 0 && <li>자주 쓰는 연결 표현: {profile.connectives.join(' · ')}</li>}
              <li className="muted">
                {profile.source_chars.toLocaleString()}자 · {profile.sentence_count}문장에서 뽑았습니다
              </li>
            </ul>
            {profile.notice && <p className="notice">{profile.notice}</p>}
          </div>

          <details className="wr-fragment">
            <summary>AI에게 전달되는 문장 보기</summary>
            <pre>{profile.prompt_fragment}</pre>
          </details>
        </>
      )}

      <div className="row">
        <button onClick={build} disabled={isBusy || short}>
          지금 글로 말투 뽑기
        </button>
        {profile && (
          <button className="secondary" onClick={remove} disabled={isBusy}>
            지우기
          </button>
        )}
      </div>

      {short && (
        <p className="muted">
          지금 글은 {text.length.toLocaleString()}자입니다. {(MIN_PROFILE_CHARS - text.length).toLocaleString()}자가
          더 필요합니다 — 글이 적으면 말투가 아니라 그 글의 우연이 잡힙니다.
        </p>
      )}
    </div>
  )
}
