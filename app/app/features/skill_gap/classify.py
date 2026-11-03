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
from collections.abc import Mapping

from app.features.matching.vocab import squash

SKILL, DOMAIN, CONDITION, NOISE = "skill", "domain", "condition", "noise"

#: 지원 조건 패턴(이름, 정규식). 순서대로 첫 일치.
CONDITION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(p))
    for name, p in (
        # 어학 점수는 사전 기술(토익·오픽)이어도 조건이다(2026-10-30 사용자 결정, kind_of에서 먼저 본다)
        ("어학", r"(?i)ESPT|TOEIC|TOEFL|TEPS|OPIc|IELTS|JLPT|JPT|HSK|토익|토플|텝스|오픽|어학"),
        ("병역", r"병역|군필|군\s*복무|미필|면제"),
        ("학력", r"학력|고졸|대졸|초대졸|전문대|학사|석사|박사|졸업(예정)?|학위"),
        ("경력", r"^경력$|경력\s*(우선|우대|무관|[:：]|\d)|\d+\s*년\s*(이상|이하|미만)|신입|경력자|유경험"
                 r"|준하는\s*경력"),
        ("전공", r"전공"),
        ("결격", r"결격|해외\s*(여행|출국)|신원|신체|건강|지원\s*(불가|제한)"),
        ("인적사항", r"남성|여성|성별|국적|연령|나이|만\s*\d+\s*세|거주|보훈|장애|취업\s*보호|지역\s*:"
                     r"|주민등록"),
        ("근무조건", r"근무\s*가능|교대|야간|주말|출장|입사\s*가능|즉시|\d{1,2}:\d{2}"
                     r"|자차|운전\s*면허|차량\s*소지"),
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
#: 보이지 않는 공백(고용24 본문에 섞여 "경력 : 무관"이 패턴을 빠져나갔다)
_ZERO_WIDTH = re.compile(r"[\u200b-\u200d\u2060\ufeff]")
#: 사람을 가리키는 끝말 — 떼면 역량 이름이 남는다("~을 보유하신 분", "~할 수 있는 분", "~보유자")
_PERSON_ENDS = (
    (re.compile(r"\s*(을|를|이|가)?\s*(보유하신|보유한|갖추신|갖춘|가지신|지니신|뛰어나신|뛰어난|우수하신|우수한)"
                r"\s*(분|자)$"), ""),
    (re.compile(r"\s*(할|하실)\s*수\s*있(는|으신)\s*(분|자)$"), ""),
    (re.compile(r"\s*경험자$"), " 경험"),
    (re.compile(r"\s*(이|가)?\s*가능한\s*(분|자)$"), ""),
    (re.compile(r"\s*(보유자|소지자|가능자|우수자|능통자)$"), ""),
)
#: 부사("원활하게 소통"의 "원활하게")
_ADV = re.compile(r"^\S+(하게|히)$")
#: 연결 어미로 끝난 잘린 문장("기본 구조를 이해하고")
_CLAUSE_ENDS = ("하고", "하며", "하여", "이고")
#: 원문 줄에 "전공"이 있을 때 전공 이름으로 보는 조각: "~과/학과/계열/학부"로 끝나거나 공백 없는 짧은 한글
_MAJOR_NAME = re.compile(r"(학과|과|계열|학부)$|^[가-힣]{2,10}$")


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
    """A11 조각을 다듬는다: 보이지 않는 공백, 짝 없는 괄호 뒤, 앞 목록 번호, 끝의 " 등",
    사람을 가리키는 끝말("~보유하신 분"), 부사·앞 관형어(2어절 이상일 때)를 뗀다."""
    t = _cut_unbalanced(_ZERO_WIDTH.sub("", text).strip())
    t = re.sub(r"^\d{1,2}\s*[.)]\s*", "", t)  # 목록 번호("7. ", "2) ")
    t = re.sub(r"\s*등$", "", t).strip()
    for pat, repl in _PERSON_ENDS:
        t = pat.sub(repl, t).strip()
    words = [w for w in t.split() if not _ADV.match(w)] or t.split()
    if len(words) >= 2 and _ADJ.match(words[0]):
        words = words[1:]
    return " ".join(words)


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
    if last.endswith(_CLAUSE_ENDS):
        return True
    return False


def _source_line(text: str, fields: Mapping[str, str | None]) -> str | None:
    """조각이 나온 공고 원문 줄. A11은 줄을 쉼표·가운뎃점으로 잘라 결과를 가나다순으로 내므로,
    "관련전공 : 자동화시스템과, 메카트로닉스과" 같은 줄의 문맥은 첫 조각에만 남는다 → 원문 줄로 되찾는다."""
    needle = squash(_ZERO_WIDTH.sub("", text))
    if not needle:
        return None
    for value in fields.values():
        for line in (value or "").splitlines():
            if needle in squash(_ZERO_WIDTH.sub("", line)):
                return line
    return None


def kind_of(
    text: str, category: str, fields: Mapping[str, str | None] | None = None
) -> tuple[str, str | None]:
    """(종류, 조건 이름). 어학 점수는 사전 기술이어도 조건. 그 밖의 사전 기술은 skill.
    조각은 원문으로 조건을 보고, 원문 줄에 "전공"이 있으면 전공 이름인지 보고, 다듬은 말로 잡음을 본다."""
    if condition_kind(text) == "어학":
        return CONDITION, "어학"
    if category != "other":
        return SKILL, None
    clean = _ZERO_WIDTH.sub("", text)
    cond = condition_kind(clean) or condition_kind(tidy(text))
    if cond:
        return CONDITION, cond
    if fields is not None and _MAJOR_NAME.search(tidy(text)):
        line = _source_line(text, fields)
        if line and re.search(r"전공|학과|계열", line):
            return CONDITION, "전공"
    if is_noise(tidy(text)):
        return NOISE, None
    return DOMAIN, None
