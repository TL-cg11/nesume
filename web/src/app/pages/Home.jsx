import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { resumesApi } from '../../features/resumes/api.js'
import { shortDate } from '../../features/resumes/ShareTags.jsx'
import './home.css'

// 홈 대시보드(사용자용) — 발표 시안 화면 1(sprint2/index.html), part2_guide 4.54
// 숫자는 B 대시보드 API(GET /resumes/dashboard) 하나로 받는다. 상태 없음은 '작성 중'으로 본다.
const STATUS_CLASS = { '작성 중': 'home-badge', '검토 중': 'home-badge review', 완료: 'home-badge done' }

const fmt = (iso) =>
  new Date(iso).toLocaleString('ko-KR', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' })

const QUICK = [
  { to: '/resumes', title: '자기소개서 작성', desc: '문항별 초안 작성과 버전 관리' },
  { to: '/experiences/new', title: '경험 등록', desc: '프로젝트와 성과를 자산으로 저장' }, // 작성 화면으로 바로(10/28)
  { to: '/writing', title: 'AI 글 다듬기', desc: '문장과 STAR 구성 점검' },
  { to: null, title: '공고 추천 · 역량 갭', desc: '요구 역량과 경험의 연결 확인' }, // C 화면 준비 중
]

function Stat({ label, value, caption }) {
  return (
    <div className="card home-stat">
      <span className="muted">{label}</span>
      <strong className="home-stat-value">{value}</strong>
      <span className="muted">{caption}</span>
    </div>
  )
}

export default function Home() {
  const navigate = useNavigate()
  const [d, setD] = useState(null)
  const [error, setError] = useState(null)
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    const ctrl = new AbortController()
    resumesApi
      .dashboard({ signal: ctrl.signal })
      .then(setD)
      .catch((e) => e.name !== 'AbortError' && setError(e.status === 401 ? '로그인 후 이용할 수 있습니다.' : e.message))
    return () => ctrl.abort()
  }, [])

  const create = async () => {
    setCreating(true)
    try {
      const r = await resumesApi.createUntitled()
      navigate(`/resumes/${r.id}`, { state: { focusTitle: true } })
    } catch (e) {
      // 50개 상한(409)이면 서버 안내 문구를 그대로 보여준다
      setError(e.status === 401 ? '로그인 후 이용할 수 있습니다.' : e.message)
      setCreating(false)
    }
  }

  return (
    <section className="home">
      <div className="card home-hero">
        <span className="home-eyebrow">AI 커리어 워크스페이스</span>
        <h1>
          나의 경험을 정리하고,
          <br />
          설득력 있는 이야기로 완성하세요.
        </h1>
        <p className="muted">경험 기록부터 자기소개서 첨삭까지, 취업 준비의 모든 단계를 한곳에서 관리하세요.</p>
        {/* 목록을 거치지 않고 바로 새 자기소개서를 만들어 상세(편집) 화면으로(10/28 요청) */}
        <button type="button" className="home-cta" onClick={create} disabled={creating}>
          {creating ? '만드는 중…' : '자기소개서 작성하기'}
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {!d && !error && <p className="muted">불러오는 중...</p>}

      {d && (
        <>
          <div className="home-stats">
            <Stat label="작성 중인 자기소개서" value={d.resume_in_progress} caption={`문서 관리 · 전체 ${d.resume_total}건`} />
            <Stat label="등록한 경험" value={d.experience_total} caption="나의 경험 자산" />
            <Stat label="전체 작성 진행률" value={`${d.progress_percent}%`} caption={`문항 본문 기준 · ${d.question_filled}/${d.question_total}`} />
            <Stat
              label="최근 저장"
              value={d.latest_save ? fmt(d.latest_save.created_at) : '—'}
              caption={
                d.latest_save
                  ? `v${d.latest_save.version_no} · ${d.latest_save.resume_title} · ${d.latest_save.question_title}`
                  : '아직 저장한 본문이 없습니다'
              }
            />
          </div>

          <div className="home-grid">
            <div className="card">
              <div className="row">
                <div className="grow">
                  <h2>최근 자기소개서</h2>
                  <p className="muted">최근 수정한 문서를 이어서 작성하세요.</p>
                </div>
                <Link to="/resumes">전체 보기</Link>
              </div>
              <ul className="list">
                {d.recent.map((r) => (
                  <li key={r.id} className="home-recent">
                    <div className="grow">
                      <Link to={`/resumes/${r.id}`} className="home-recent-title">
                        {r.title}
                      </Link>
                      <p className="muted">
                        {r.question_count}개 문항 · {fmt(r.last_edited_at)} 수정
                        {r.share_summary &&
                          ` · 멘토 공유 중 (만료 ${shortDate(r.share_summary.earliest_end_date)})`}
                      </p>
                    </div>
                    <span className={STATUS_CLASS[r.status ?? '작성 중'] ?? 'home-badge'}>{r.status ?? '작성 중'}</span>
                  </li>
                ))}
                {d.recent.length === 0 && <li className="muted">아직 자기소개서가 없습니다.</li>}
              </ul>
            </div>

            <div className="home-side">
              <div className="card">
                <h2>빠른 시작</h2>
                <p className="muted">취업 준비를 효율적으로 시작하세요.</p>
                <ul className="list">
                  {QUICK.map((q) => (
                    <li key={q.title} className={q.to ? 'home-quick' : undefined}>
                      {q.to ? (
                        <Link to={q.to} className="home-quick-title">
                          {q.title}
                        </Link>
                      ) : (
                        <span className="home-quick-title muted">{q.title} (준비 중)</span>
                      )}
                      <p className="muted">{q.desc}</p>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="card home-tip">
                <h3>작성 팁</h3>
                <p>
                  상황과 과제, 구체적인 행동, 측정 가능한 결과(STAR)를 기록하면 더 설득력 있는 자기소개서를 만들 수 있습니다.
                </p>
              </div>
            </div>
          </div>
        </>
      )}
    </section>
  )
}
