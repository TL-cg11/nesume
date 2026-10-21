"""부작용 없는 세 연산 — validate_input / detect / mask.

이 세 함수는 DB도 네트워크도 모른다. 입력과 출력만으로 테스트가 끝난다.
치환표가 필요한 tokenize/detokenize 는 tokens.py 에 따로 둔다.
"""

from __future__ import annotations

import re

from app.pii.rules import Span, scan
from app.pii.types import (
    REJECTED_KINDS,
    BlockedKind,
    Hit,
    ValidationResult,
)

#: 마스킹할 때 남길 뒷자리 수의 **기본값은 0** — 전부 가린다.
#:
#: 처음에는 4로 두었다. 1차 프로젝트에서 "로그에서 같은 값인지 대조하려면 뒷자리가
#: 필요하다"고 판단했기 때문이다. 2차에서는 그 근거가 사라졌다 —
#: 감사 로그(B3)에 ``query_hash``(원문 SHA-256)가 따로 있어 **대조는 해시가 맡는다.**
#: 그래서 뒷자리를 남기는 것은 이득 없이 PII 만 남기는 일이 된다
#: (spec 15장 "감사 로그에 PII 유입" 리스크).
#:
#: 대조용 꼬리가 꼭 필요한 호출자는 ``keep_tail=4`` 로 명시한다.
DEFAULT_MASK_TAIL = 0


def detect(text: str) -> list[Hit]:
    """찾기만 한다. 바꾸지 않는다.

    "이 자소서에 개인정보가 몇 개 있습니다"를 보여주는 화면, 3번 파트가 공고 텍스트를
    점검할 때 쓴다. 치환까지 할 필요 없이 알고만 싶을 때가 많다 (제안서 4장).
    """
    if not text:
        return []
    return [
        Hit(
            kind=span.rule.kind,
            rule_id=span.rule.rule_id,
            start=span.start,
            end=span.end,
            confidence=span.rule.confidence,
        )
        for span in scan(text)
    ]


def validate_input(text: str) -> ValidationResult:
    """받으면 안 되는 입력인가.

    주민번호·계좌번호는 자소서에 들어갈 이유가 없으므로 탐지 후 저장이 아니라
    애초에 받지 않는다 (CLAUDE.md 절대 규칙 5번).

    ★ 거절 사유에 입력값을 되비추지 않는다. 되비추면 그 화면과 로그에 주민번호가 또 남는다.
    """
    counts: dict[str, int] = {}
    for hit in detect(text):
        if hit.kind in REJECTED_KINDS:
            counts[hit.kind] = counts.get(hit.kind, 0) + 1

    blocked = [BlockedKind(kind=k, count=c) for k, c in sorted(counts.items())]  # type: ignore[arg-type]
    return ValidationResult(ok=not blocked, blocked=blocked)


def mask(text: str, *, keep_tail: int = DEFAULT_MASK_TAIL) -> str:
    """되돌릴 수 없게 가린다. 로그에 남길 때만 쓴다.

    치환표를 만들지 않으므로 부작용이 없고 아무 데서나 불러도 된다.
    3번 파트가 공고 본문을 임베딩 전에 지울 때도 이걸 쓴다 — 공고의 담당자 이름은
    복원할 일이 없으니 치환표를 만들지 않는 것이 맞다 (제안서 9장).

    ``keep_tail`` 은 전화번호·계좌 같은 숫자의 뒷자리를 몇 개 남길지다.
    기본값 0 은 **전부 가린다**. 이유는 ``DEFAULT_MASK_TAIL`` 주석 참조.

    ★ 이 함수가 가리는 것은 **탐지된 것뿐**이다. 라벨 없는 단독 이름처럼 탐지되지
      않는 값은 그대로 남는다. 감사 로그처럼 "PII 가 없어야 하는" 자리에서는
      이 한계를 전제로 설계해야 한다 (호출자 책임).
    """
    if not text:
        return text

    out: list[str] = []
    cursor = 0
    for span in scan(text):
        out.append(text[cursor : span.start])
        out.append(_mask_value(span.value, span.rule.kind, keep_tail))
        cursor = span.end
    out.append(text[cursor:])
    return "".join(out)


def _mask_value(value: str, kind: str, keep_tail: int) -> str:
    """종류에 따라 가리는 모양을 달리한다."""
    if kind == "EMAIL":
        local, _, domain = value.partition("@")
        if keep_tail <= 0:
            # 도메인도 가린다. 개인 메일 도메인은 소속을 드러낸다
            return "***@***"
        head = local[0] if local else ""
        return f"{head}***@{domain}"

    if kind in {"RRN", "ACCOUNT"}:
        # 거절 대상은 어떤 경우에도 뒷자리를 남기지 않는다
        return re.sub(r"\d", "*", value)

    if keep_tail <= 0:
        return re.sub(r"\d", "*", value)

    digits = re.sub(r"\D", "", value)
    if len(digits) > keep_tail:
        # 구분자는 살리고 숫자만 가린다. 010-****-5678 모양
        tail = digits[-keep_tail:]
        masked_head = re.sub(r"\d", "*", value[: -len(tail)])
        return f"{masked_head}{tail}"

    return "*" * len(value)
