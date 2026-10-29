"""C10 — A11 요건을 학습 관점 3종으로 나눈다: 기술 역량 / 직무 역량 / 지원 조건.

A11 `extract`는 사전(vocab)에 있는 기술은 `category` 8종으로, **사전에 없는 문장 조각은 전부 `other`**로 낸다.
`other`에는 진짜 직무 역량(IFRS17·계리소프트웨어)과 **지원 조건**(병역·학력·경력 연수·인적사항)이 섞인다.
학습 로드맵은 "배울 수 있는 것"만 넣어야 하므로 여기서 가른다(docs/C10.md 3단계 분류).

- 기술 역량(`skill`): 사전 기술(`category != "other"`) — 로드맵 기본 포함, 강좌 매칭 정확
- 직무 역량(`domain`): `other` 중 조건·잡음이 아닌 것 — 사용자가 고르면 로드맵에(강좌 매칭은 약할 수 있음)
- 지원 조건(`condition`): `other` 중 아래 패턴 — 화면에 참고로만, 로드맵엔 안 넣음

규칙 기반(공고 10건 실측: other 52개 중 조건 22개 정확 분류). 장기적으로는 A11에 `condition` 분류를
두는 게 맞다(A 협의 — 사전·분류 소유가 A11). 그때는 이 모듈의 패턴 대신 그 값을 쓴다.

A11 조각은 문장을 자른 것이라 끝이 덜 닫히거나 조사가 붙는다. 진짜 역량이 앞에 있는 경우가 많아
**지우기보다 다듬는다**(`tidy`: 짝 없는 괄호 뒤·끝 "등"·앞 관형어 제거) — docs/C10.md 실측(2026-10-29).
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
        ("경력", r"경력\s*\d|\d+\s*년\s*(이상|이하|미만)|신입|경력\s*무관|경력자|유경험|준하는\s*경력"),
        ("전공", r"전공"),
        ("결격", r"결격|해외\s*(여행|출국)|신원|신체|건강"),
        ("인적사항", r"남성|여성|성별|연령|나이|만\s*\d+\s*세|거주|보훈|장애|취업\s*보호|지역\s*:|주민등록"),
        ("근무조건", r"근무\s*가능|교대|야간|주말|출장|입사\s*가능|즉시|\d{1,2}:\d{2}"),
        ("일정", r"\d{4}\s*년|\d{1,2}\s*월(?!급)|\d{4}\s*[.\-/]\s*\d{1,2}"),
        ("고용형태", r"정규직|계약직|인턴|파견|아르바이트"),
        ("직급", r"^(사원|주임|대리|과장|차장|부장|선임|책임|팀원|팀장)급?$"),
    )
)

#: 역량이 아닌 범용 단어(조각만 남은 머리말 등)
_GENERIC = frozenset({
    "응시자격", "지원자격", "자격요건", "자격", "우대", "우대사항", "필수", "공통", "기타", "등",
})
_ALNUM = re.compile(r"[0-9A-Za-z가-힣]")
#: 조직·범용 단어 — 조각이 이것들로만 되어 있으면 역량이 아니다("대외 기관")
_ORG_WORDS = frozenset({"대외", "내부", "유관", "기관", "부서", "관련", "업무", "협력", "고객"})
#: 앞에 붙은 관형어("원활한 커뮤니케이션"의 "원활한")
_ADJ = re.compile(r"^\S+(한|된|적인)$")
#: 조사·어미로 끝난 어절 — 문장이 중간에 잘린 조각("~와의 소통 시", "복잡한 법적")
_PARTICLE_WORDS = frozenset({"시", "및", "등"})
_PARTICLE_ENDS = ("와의", "과의", "에서", "으로")
#: 짝 없는 `)` 뒤에 남는 앞 조사("외부감사인)와의 협업"의 "와의")
_LEAD_PARTICLE = re.compile(r"^(와의|과의|에서|으로|와|과|의|에|로|를|을|이|가)\s*")


def _cut_unbalanced(text: str) -> str:
    """짝 없는 괄호를 잘라낸다: 열린 `(`는 그 뒤를, 닫힌 `)`는 그 앞을 버린다."""
    for op, cl in (("(", ")"), ("[", "]")):
        depth, cut_from = 0, None
        for i, ch in enumerate(text):
            if ch == op:
                if depth == 0:
                    cut_from = i
                depth += 1
            elif ch == cl:
                if depth == 0:  # 짝 없는 닫힘 — 앞부분은 다른 문장의 꼬리, 뒤에 남은 조사도 뗀다
                    rest = _LEAD_PARTICLE.sub("", text[i + 1:].lstrip())
                    return _cut_unbalanced(rest)
                depth -= 1
        if depth > 0 and cut_from is not None:
            text = text[:cut_from]
    return text.strip()


def tidy(text: str) -> str:
    """A11 조각을 다듬는다: 짝 없는 괄호 뒤, 앞 목록 번호, 끝의 " 등", 앞 관형어(2어절 이상일 때)를 뗀다."""
    t = _cut_unbalanced(text.strip())
    t = re.sub(r"^\d{1,2}\s*[.)]\s*", "", t)  # 목록 번호("7. ", "2) ")
    t = re.sub(r"\s*등$", "", t).strip()
    words = t.split()
    if len(words) >= 2 and _ADJ.match(words[0]):
        t = " ".join(words[1:])
    return t


def condition_kind(text: str) -> str | None:
    """지원 조건이면 그 이름(병역·학력 …), 아니면 None."""
    for name, pat in CONDITION_PATTERNS:
        if pat.search(text):
            return name
    return None


def is_noise(text: str) -> bool:
    """역량으로 보기 어려운 조각: 2자 미만, 글자 없음, 범용 머리말, 엔티티 잔재, 안내문(※),
    조직·범용 단어뿐, 조사·어미로 끝나 문장이 잘린 것."""
    t = text.strip()
    if len(_ALNUM.findall(t)) < 2 or t in _GENERIC or "&" in t or t.startswith("※"):
        return True
    words = t.split()
    if all(w in _ORG_WORDS for w in words):
        return True
    last = words[-1]
    if last in _PARTICLE_WORDS or last.endswith(_PARTICLE_ENDS) or (len(last) <= 3 and last.endswith("적")):
        return True
    return False


def kind_of(text: str, category: str) -> tuple[str, str | None]:
    """(종류, 조건 이름). 사전 기술은 항상 skill. 조각은 원문으로 조건을 보고, 다듬은 말로 잡음을 본다."""
    if category != "other":
        return SKILL, None
    cond = condition_kind(text) or condition_kind(tidy(text))
    if cond:
        return CONDITION, cond
    if is_noise(tidy(text)):
        return NOISE, None
    return DOMAIN, None
