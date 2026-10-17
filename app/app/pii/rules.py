"""탐지 규칙 정의와 겹침 해소.

1차 프로젝트에서 배운 것 하나를 설계에 반영했다.
거기서는 규칙을 배열 순서대로 적용했는데, PHONE 규칙이 RRN 규칙보다 앞에 있어서
주민번호 `9001011234567` 이 전화번호로 잘못 분류됐다. 규칙을 추가할 때마다
순서를 신경 써야 하는 구조 자체가 문제였다.

그래서 여기서는 규칙마다 **priority 를 명시**하고, 겹치는 구간은 priority 로만
해소한다. 선언 순서는 결과에 영향을 주지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from app.pii.types import Confidence, PiiKind


@dataclass(frozen=True)
class Rule:
    kind: PiiKind
    rule_id: str
    pattern: re.Pattern[str]
    #: 클수록 먼저 차지한다. 겹치면 priority 가 높은 쪽이 이긴다.
    priority: int
    confidence: Confidence = "high"
    #: 정규식만으로 부족할 때 쓰는 추가 검사. True 를 돌려줘야 채택한다.
    validator: Callable[[str], bool] | None = None
    #: 치환할 부분. 0이면 매치 전체, 1 이상이면 그 캡처 그룹만.
    #: 라벨이 붙은 규칙("이름: 김철수")에서 라벨은 두고 값만 바꾸기 위해 쓴다.
    group: int = 0


@dataclass(frozen=True)
class Span:
    """규칙이 차지한 구간 하나. 치환·마스킹은 이 구간에만 적용한다."""

    rule: Rule
    start: int
    end: int
    value: str


# --------------------------------------------------------------------------
# 거절 대상 — 가장 높은 우선순위. 다른 규칙이 가로채면 거절 자체가 무력해진다
# --------------------------------------------------------------------------

def _valid_rrn_date(value: str) -> bool:
    """주민번호 앞 6자리가 날짜로 말이 되는지 본다. 임의의 13자리 숫자 오탐을 줄인다."""
    digits = re.sub(r"\D", "", value)
    if len(digits) < 7:
        return False
    month, day = int(digits[2:4]), int(digits[4:6])
    return 1 <= month <= 12 and 1 <= day <= 31


RRN = Rule(
    kind="RRN",
    rule_id="PII_RRN",
    # 생년월일 6자리 + 구분자 + 성별코드(1~4, 외국인 5~8) + 6자리
    pattern=re.compile(r"(?<!\d)\d{6}[-\s.]?[1-8]\d{6}(?!\d)"),
    priority=100,
    validator=_valid_rrn_date,
)

EMAIL = Rule(
    kind="EMAIL",
    rule_id="PII_EMAIL",
    pattern=re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    priority=95,
)

PHONE = Rule(
    kind="PHONE",
    rule_id="PII_PHONE",
    # 국내 휴대폰 + 국제표기(+82). 1차에서 +82 형식을 놓쳤던 것을 처음부터 넣는다.
    # 앞뒤 숫자 경계를 막아 더 긴 숫자열의 일부를 잘라내지 않게 한다.
    pattern=re.compile(
        r"(?<!\d)(?:\+82[-.\s]?(?:\(0\)[-.\s]?)?1[016789]|\(?01[016789]\)?)"
        r"[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)"
    ),
    # ★ ACCOUNT 보다 높다. 전화번호는 계좌번호와 모양이 겹치는데 형식이 더 구체적이므로
    #   (01X 또는 +82로 시작) 먼저 차지해야 한다. 반대로 두면 010-1234-5678 이
    #   계좌번호로 잡힌다 — 1차에서 PHONE 이 RRN 을 가로챘던 것과 같은 종류의 버그다.
    priority=90,
)


def _plausible_account(value: str) -> bool:
    """계좌번호로 볼 만한가.

    구분자로 끊은 숫자 묶음은 날짜·전화번호·버전과 모양이 겹친다.
    자릿수와 접두사로 거른다.
    """
    digits = re.sub(r"\D", "", value)
    if not (10 <= len(digits) <= 16):
        return False  # 2024-01-15 같은 날짜(8자리)를 거른다
    if re.match(r"01[016789]", digits):
        return False  # 전화번호는 PHONE 이 맡는다
    return True


ACCOUNT = Rule(
    kind="ACCOUNT",
    rule_id="PII_ACCOUNT",
    # 계좌·카드번호. 10~16자리를 구분자로 끊어 적는 흔한 형태
    pattern=re.compile(r"(?<!\d)\d{2,6}[-\s]\d{2,6}[-\s]\d{2,6}(?:[-\s]\d{1,6})?(?!\d)"),
    priority=85,
    confidence="low",  # 숫자 묶음은 다른 것과 겹친다. 호출자가 정책을 고른다
    validator=_plausible_account,
)

# --------------------------------------------------------------------------
# 미정 — 킥오프(10/20)에서 정해야 구현할 수 있는 규칙들
# --------------------------------------------------------------------------
# 제안서 10장 질문 3·4가 여기에 해당한다.
#
#   Q3. PII_ORG · PII_SCHOOL 을 규칙 목록에 추가할 것인가
#       → CLAUDE.md 의 탐지 규칙 ID 목록에는 아직 없다. 목록을 고치는 일이라 팀 합의가 필요하다.
#   Q4. 학교·수상명·프로젝트명을 어디까지 토큰화할 것인가
#       → 많이 치환할수록 안전하지만 모델이 맥락을 잃어 글이 나빠진다. 품질과 보호의 맞교환.
#
# PERSON 은 규칙 목록에 이미 PII_NAME 으로 있지만, 1차에서 가장 어려웠던 항목이다.
# "김철수입니다" 처럼 라벨 없는 단독 이름은 끝내 미탐으로 남았다.
# 맥락 단서(라벨·조사·전화번호 인접) 없이 한국어 이름만으로 판정하면 일반 명사를
# 대량 오탐한다. 규칙을 세우기 전에 Q4 의 기준선이 먼저 필요하다.

PERSON_LABELED = Rule(
    kind="PERSON",
    rule_id="PII_PERSON",
    # 1단계: 라벨이 붙은 이름만 잡는다. 오탐이 거의 없는 안전한 출발점.
    # 라벨 없는 단독 이름은 Q4 결정 후 별도 규칙으로 추가한다.
    pattern=re.compile(
        r"(?:이름|성함|성명|지원자|작성자)\s*[:：]?\s*([가-힣]{2,4})(?![가-힣])"
    ),
    priority=40,
    # ★ 라벨은 두고 이름만 치환한다. 매치 전체를 바꾸면 "이름:" 까지 토큰에 먹혀
    #   모델이 문서 구조를 잃는다.
    group=1,
)

#: 활성 규칙. 미정 항목이 정해지면 여기에 추가한다.
ACTIVE_RULES: tuple[Rule, ...] = (
    RRN,
    ACCOUNT,
    EMAIL,
    PHONE,
    PERSON_LABELED,
)

#: 아직 규칙이 없는 종류. detect() 가 이 종류를 돌려주는 일은 없다.
#: 호출자가 "안 나온 것"과 "아직 못 잡는 것"을 구분할 수 있게 명시해 둔다.
NOT_YET_DETECTED: frozenset[str] = frozenset({"ORG", "SCHOOL", "ADDRESS"})


def scan(text: str) -> list[Span]:
    """모든 활성 규칙을 적용하고 겹치는 구간을 priority 로 해소한다.

    같은 구간을 두 규칙이 잡으면 priority 가 높은 쪽만 남긴다.
    priority 가 같으면 더 긴 쪽, 그것도 같으면 앞쪽을 택한다.
    선언 순서는 결과에 영향을 주지 않는다.
    """
    if not text:
        return []

    candidates: list[Span] = []
    for rule in ACTIVE_RULES:
        for match in rule.pattern.finditer(text):
            if rule.validator is not None and not rule.validator(match.group(0)):
                continue
            value = match.group(rule.group)
            if not value:
                continue
            candidates.append(
                Span(
                    rule=rule,
                    start=match.start(rule.group),
                    end=match.end(rule.group),
                    value=value,
                )
            )

    ordered = sorted(
        candidates,
        key=lambda s: (-s.rule.priority, -(s.end - s.start), s.start),
    )
    chosen: list[Span] = []
    for span in ordered:
        if any(span.start < c.end and c.start < span.end for c in chosen):
            continue
        chosen.append(span)
    return sorted(chosen, key=lambda s: s.start)
