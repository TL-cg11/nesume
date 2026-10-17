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

#: 마스킹할 때 남길 뒷자리 수. 로그에서 같은 값인지 대조할 수 있을 만큼만 남긴다.
_MASK_TAIL = 4


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


def mask(text: str) -> str:
    """되돌릴 수 없게 가린다. 로그에 남길 때만 쓴다.

    치환표를 만들지 않으므로 부작용이 없고 아무 데서나 불러도 된다.
    3번 파트가 공고 본문을 임베딩 전에 지울 때도 이걸 쓴다 — 공고의 담당자 이름은
    복원할 일이 없으니 치환표를 만들지 않는 것이 맞다 (제안서 9장).
    """
    if not text:
        return text

    out: list[str] = []
    cursor = 0
    for span in scan(text):
        out.append(text[cursor : span.start])
        out.append(_mask_value(span.value, span.rule.kind))
        cursor = span.end
    out.append(text[cursor:])
    return "".join(out)


def _mask_value(value: str, kind: str) -> str:
    """종류에 따라 가리는 모양을 달리한다. 뒷자리를 조금 남겨 대조만 가능하게 한다."""
    if kind == "EMAIL":
        local, _, domain = value.partition("@")
        head = local[0] if local else ""
        return f"{head}***@{domain}"

    if kind in {"RRN", "ACCOUNT"}:
        # 거절 대상은 뒷자리도 남기지 않는다. 로그에 남을 이유가 없는 값이다.
        return re.sub(r"\d", "*", value)

    digits = re.sub(r"\D", "", value)
    if len(digits) > _MASK_TAIL:
        # 구분자는 살리고 숫자만 가린다. 010-****-5678 모양
        tail = digits[-_MASK_TAIL:]
        masked_head = re.sub(r"\d", "*", value[: -len(tail)]) if tail else value
        return f"{masked_head}{tail}"

    return "*" * len(value)
