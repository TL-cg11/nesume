// 문장 제안과 질문 (A11).
//
// 이 화면에서 가장 조심할 곳이다. 두 가지를 **섞어 보여주지 않는다.**
//
//   hints      경험엔 있는데 자소서에 안 쓴 요건 → 붙여 쓸 문장. 근거(경험 이름)가 있다
//   questions  근거가 아예 없는 요건 → 문장이 아니라 **질문**. 지어내면 면접에서 드러난다
//
// ★ `notice`(service.NO_INVENTION_NOTICE)는 서버가 "질문 목록 위에 반드시 함께
//   보여줄 안내" 로 내려준다. 질문을 보여주면서 이 문구를 빼지 않는다.
// ★ 제안 문장은 모델이 만든 글이라 근거를 함께 보여준다. 확인 없이 쓰라고 권하지 않는다.

export default function HintPanel({ hints, questions, notice, droppedHints }) {
  const hasAny = hints.length > 0 || questions.length > 0
  if (!hasAny) return null

  return (
    <div className="stack">
      {hints.length > 0 && (
        <section className="card mt-hints">
          <strong>자소서에 넣을 문장 {hints.length}개</strong>
          <p className="muted">
            경험에 있는 내용으로 만든 문장입니다. 사실이 맞는지 확인한 뒤 쓰십시오.
          </p>
          <ul className="list">
            {hints.map((h) => (
              <li key={h.keyword} className="mt-hint">
                <div className="head">
                  <strong className="grow">{h.keyword}</strong>
                  <span className="mt-badge check">확인 필요</span>
                </div>
                <p>{h.sentence}</p>
                {h.experiences.length > 0 && (
                  <p className="muted">근거: {h.experiences.join(', ')}</p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {questions.length > 0 && (
        <section className="card mt-questions">
          <strong>근거가 없는 요건에 대한 질문 {questions.length}개</strong>
          {/* 서버가 내려준 안내를 그대로 둔다 */}
          <p className="notice">{notice}</p>
          <ul className="list">
            {questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </section>
      )}

      {droppedHints > 0 && (
        <p className="notice">
          제안 문장 {droppedHints}개는 경험에 없는 내용이 섞여 버렸습니다.
        </p>
      )}
    </div>
  )
}
