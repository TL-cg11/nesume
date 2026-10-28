// A14 — 내 말투. 다시 쓰기 탭 아래에 접어 둔다.
//
// ★ 본인만 볼 수 있다. 멘토·운영자도 조회할 수 없다 (tasks.md A14).
// ★ 프롬프트에 들어가는 문단을 그대로 보여준다 — 무엇이 모델에 가는지 사용자가 알아야 한다.
// ★ 지울 수 있어야 한다. 사용자가 만들라고 한 적 없는 파생 데이터다.
//
// 처음 읽기는 페이지 공용 run 을 쓰지 않는다. run 은 진행 중인 요청을 취소하므로,
// 탭을 여는 것만으로 검사·다시 쓰기 요청이 끊기면 안 된다.

import { useEffect, useState } from 'react'
import { MIN_PROFILE_CHARS, profileApi } from './api.js'

export default function ProfileBox({ text, run, isBusy }) {
  const [profile, setProfile] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [note, setNote] = useState(null)

  useEffect(() => {
    const ctrl = new AbortController()
    profileApi
      .read(ctrl.signal)
      .then(setProfile)
      // 404 는 "아직 없음" 이다. 다른 오류도 이 상자 밖으로 내지 않는다 — 다시 쓰기는 말투 없이도 된다
      .catch(() => null)
      .finally(() => !ctrl.signal.aborted && setLoaded(true))
    return () => ctrl.abort()
  }, [])

  const build = async () => {
    setNote(null)
    const body = await run((signal) => profileApi.build(text, signal))
    if (!body) return
    setProfile(body)
    setNote('지금 글로 말투를 다시 뽑았습니다. 다음 다시 쓰기부터 반영됩니다.')
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
    <details className="card wr-profile">
      <summary>
        <strong>내 말투</strong>
        {!loaded ? (
          <span className="muted"> 불러오는 중...</span>
        ) : profile ? (
          <span className="wr-badge llm">반영 중</span>
        ) : (
          <span className="wr-badge">꺼짐</span>
        )}
        <span className="muted"> — 평소 문체를 뽑아 두면 다시 쓸 때 그 문체에 맞춥니다</span>
      </summary>

      <div className="stack">
        <p className="muted">
          <strong>본인만 볼 수 있습니다</strong> — 멘토·운영자도 조회할 수 없습니다.
        </p>
        {note && <p className="success">{note}</p>}

        {profile ? (
          <>
            <ul className="list">
              <li>
                문장 평균 {profile.avg_sentence_len}자 · 문단당 문장 {profile.paragraph_avg_sentences}개
                {profile.thin && <span className="wr-badge check">표본 적음</span>}
              </li>
              {profile.endings.length > 0 && <li>자주 쓰는 문장 끝: {profile.endings.join(' · ')}</li>}
              {profile.connectives.length > 0 && <li>자주 쓰는 연결 표현: {profile.connectives.join(' · ')}</li>}
              <li className="muted">
                {profile.source_chars.toLocaleString()}자 · {profile.sentence_count}문장에서 뽑았습니다
              </li>
            </ul>
            {profile.notice && <p className="notice">{profile.notice}</p>}
            <details className="wr-fragment">
              <summary>AI에게 전달되는 문장 보기</summary>
              <pre>{profile.prompt_fragment}</pre>
            </details>
          </>
        ) : (
          loaded && (
            <p className="muted">
              아직 없습니다. 내가 쓴 글 {MIN_PROFILE_CHARS.toLocaleString()}자 이상을 왼쪽에 넣고 뽑으십시오.
            </p>
          )
        )}

        <div className="row">
          <button className="secondary" onClick={build} disabled={isBusy || short}>
            {profile ? '지금 글로 다시 뽑기' : '지금 글로 말투 뽑기'}
          </button>
          {profile && (
            <button className="secondary" onClick={remove} disabled={isBusy}>
              지우기
            </button>
          )}
          {short && (
            <span className="muted">
              {(MIN_PROFILE_CHARS - text.length).toLocaleString()}자 더 필요합니다
            </span>
          )}
        </div>
      </div>
    </details>
  )
}
