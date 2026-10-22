// 제안 한 건. 글을 바꾸는 제안만 체크박스를 둔다.
//
// 안내만 하는 항목(상투어·긴 문장·STAR 보완)은 '무엇으로 바꿀지'를 글쓴이만 알기 때문에
// 서버가 대안을 만들지 않는다. 체크박스를 두면 "수락했는데 아무 일도 안 일어난다"가 된다.

export default function SuggestionItem({ item, checked, onToggle }) {
  const isLlm = item.source === 'llm'
  const needsCheck = item.confidence === 'medium'

  return (
    <li className={item.is_replacement ? 'wr-item' : 'wr-item guidance'}>
      <div className="head">
        {item.is_replacement ? (
          <input
            type="checkbox"
            checked={checked}
            onChange={() => onToggle(item.id)}
            aria-label={`${item.original} 수정 반영`}
          />
        ) : (
          <span className="wr-badge">안내</span>
        )}
        <span className="wr-badge">{item.rule_id}</span>
        {isLlm && <span className="wr-badge llm">AI 제안</span>}
        {needsCheck && (
          // 근거를 댈 수 없는 제안이다. 규칙 제안과 같은 무게로 보이면
          // 사용자가 구분 없이 수락하게 된다.
          <span className="wr-badge check" title="규칙으로 확정할 수 없어 직접 판단이 필요합니다">
            확인 필요
          </span>
        )}
      </div>

      {item.is_replacement ? (
        <p>
          <span className="wr-from">{item.original}</span>
          {' → '}
          <span className="wr-to">{item.suggested}</span>
        </p>
      ) : (
        item.original && <p>{`"${item.original}"`}</p>
      )}

      <p className="reason">{item.reason}</p>
    </li>
  )
}
