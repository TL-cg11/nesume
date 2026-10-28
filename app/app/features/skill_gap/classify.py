"""C10 — A11 요건을 학습 관점 3종으로 나눈다: 기술 역량 / 직무 역량 / 지원 조건.

A11 `extract`는 사전(vocab)에 있는 기술은 `category` 8종으로, **사전에 없는 문장 조각은 전부 `other`**로 낸다.
`other`에는 진짜 직무 역량(IFRS17·계리소프트웨어)과 **지원 조건**(병역·학력·경력 연수·인적사항)이 섞인다.
학습 로드맵은 "배울 수 있는 것"만 넣어야 하므로 여기서 가른다(docs/C10.md 3단계 분류).

- 기술 역량(`skill`): 사전 기술(`category != "other"`) — 로드맵 기본 포함, 강좌 매칭 정확
- 직무 역량(`domain`): `other` 중 조건·잡음이 아닌 것 — 사용자가 고르면 로드맵에(강좌 매칭은 약할 수 있음)
- 지원 조건(`condition`): `other` 중 아래 패턴 — 화면에 참고로만, 로드맵엔 안 넣음

규칙 기반(공고 10건 실측: other 52개 중 조건 22개 정확 분류). 장기적으로는 A11에 `condition` 분류를
두는 게 맞다(A 협의 — 사전·분류 소유가 A11). 그때는 이 모듈의 패턴 대신 그 값을 쓴다.
"""
from __future__ import annotations

import re

SKILL, DOMAIN, CONDITION, NOISE = "skill", "domain", "condition", "noise"

#: 지원 조건 패턴(이름, 정규식). 순서대로 첫 일치.
CONDITION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(p))
    for name, p in (
        ("병역", r"병역|군필|군\s*복무|미필|면제"),
        ("학력", r"학력|고졸|대졸|초대졸|전문대|학사|석사|박사|졸업(예정)?|학위"),
        ("경력", r"경력\s*\d|\d+\s*년\s*(이상|이하|미만)|신입|경력\s*무관|경력자|유경험"),
        ("전공", r"전공"),
        ("결격", r"결격|해외\s*(여행|출국)|신원|신체|건강"),
        ("인적사항", r"남성|여성|성별|연령|나이|만\s*\d+\s*세|거주|보훈|장애|취업\s*보호"),
        ("근무조건", r"근무\s*가능|교대|야간|주말|출장|입사\s*가능|즉시"),
    )
)

#: 역량이 아닌 범용 단어(조각만 남은 머리말 등)
_GENERIC = frozenset({
    "응시자격", "지원자격", "자격요건", "자격", "우대", "우대사항", "필수", "공통", "기타", "등",
})
_ALNUM = re.compile(r"[0-9A-Za-z가-힣]")


def condition_kind(text: str) -> str | None:
    """지원 조건이면 그 이름(병역·학력 …), 아니면 None."""
    for name, pat in CONDITION_PATTERNS:
        if pat.search(text):
            return name
    return None


def is_noise(text: str) -> bool:
    """역량으로 보기 어려운 조각: 2자 미만, 글자 없음, 범용 머리말, 엔티티 잔재."""
    t = text.strip()
    if len(_ALNUM.findall(t)) < 2 or t in _GENERIC or "&" in t:
        return True
    return False


def kind_of(text: str, category: str) -> tuple[str, str | None]:
    """(종류, 조건 이름). 사전 기술은 항상 skill."""
    if category != "other":
        return SKILL, None
    cond = condition_kind(text)
    if cond:
        return CONDITION, cond
    if is_noise(text):
        return NOISE, None
    return DOMAIN, None
