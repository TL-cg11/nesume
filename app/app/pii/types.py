"""PII 공용 모듈의 계약 타입.

여기 적힌 타입 이름과 필드 구성이 세 파트가 공유하는 계약이다.
구현을 바꾸는 것은 자유지만 이 파일을 바꾸면 2·3번 파트 코드가 같이 깨진다.
제안서 v0.1 3장 참조.
"""

from dataclasses import dataclass
from typing import Literal

# 토큰화 대상과 거절 대상을 한 타입에 둔다.
# 두 집합을 나누면 Hit.kind 를 쓰는 쪽이 두 타입을 받아야 해서 호출부가 복잡해진다.
PiiKind = Literal[
    # 토큰화 대상 — 복원이 필요하다
    "PERSON",
    "ORG",
    "SCHOOL",
    "PHONE",
    "EMAIL",
    "ADDRESS",
    # 거절 대상 — 자소서에 들어갈 이유가 없다. 받지 않는다
    "RRN",
    "ACCOUNT",
]

#: validate_input() 이 거절하는 종류. CLAUDE.md 절대 규칙 5번.
REJECTED_KINDS: frozenset[str] = frozenset({"RRN", "ACCOUNT"})

#: tokenize() 가 기본으로 치환하는 종류.
TOKENIZED_KINDS: tuple[PiiKind, ...] = (
    "PERSON",
    "ORG",
    "SCHOOL",
    "PHONE",
    "EMAIL",
    "ADDRESS",
)

Confidence = Literal["high", "low"]


@dataclass(frozen=True)
class Hit:
    """탐지된 PII 하나.

    ★ 원문 값을 담지 않는다. Hit 은 로그·화면으로 흘러갈 가능성이 높은 구조체다.
      값이 필요하면 치환표(Vault)를 본다. 1차 프로젝트에서 탐지 근거에 원문을
      넣지 않은 것과 같은 판단이다.
    """

    kind: PiiKind
    rule_id: str  # "PII_PERSON" 등. CLAUDE.md 탐지 규칙 ID 목록과 일치해야 한다
    start: int  # 원문에서의 시작 위치
    end: int  # 끝 위치 (포함하지 않음, 반열림 구간)
    confidence: Confidence
    token: str | None = None  # 치환했을 때만 채운다. detect() 결과에서는 항상 None


@dataclass(frozen=True)
class BlockedKind:
    """거절 사유 하나. 종류와 개수만 담고 값은 담지 않는다."""

    kind: PiiKind
    count: int


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    blocked: list[BlockedKind]


@dataclass(frozen=True)
class TokenizeResult:
    text: str  # 치환된 본문. 이것만 LLM에 보낸다
    vault_id: str
    hits: list[Hit]
    counts: dict[str, int]  # 종류별 개수. 키는 PiiKind


@dataclass(frozen=True)
class DetokenizeResult:
    text: str
    #: 치환표에 없어서 복원하지 못한 토큰 목록.
    #: 비어 있어야 정상이다. 비어 있지 않으면 호출자가 재생성을 유도한다 (제안서 7장).
    unresolved: list[str]


#: 필드 하나의 값. 경험 데이터의 태그·사용 기술처럼 배열인 필드가 있다 (B5).
FieldValue = str | list[str]


@dataclass(frozen=True)
class FieldsTokenizeResult:
    """여러 필드를 치환표 하나로 묶은 결과.

    자소서 한 건은 문항이 여럿이고, 같은 전화번호가 여러 문항에 나온다.
    필드마다 따로 치환하면 같은 값이 문항마다 다른 토큰을 받아 모델이 다른
    사람으로 읽고, 치환표도 문항 수만큼 생긴다 (B4·B5 요청).
    """

    #: 입력과 같은 키·같은 모양(문자열은 문자열, 배열은 배열), 값만 치환된 본문
    texts: dict[str, FieldValue]
    vault_id: str
    #: 필드별 탐지 결과.
    #: 배열 필드는 원소마다 ``"tags[0]"`` 처럼 색인을 붙인 키를 쓴다 —
    #: Hit 의 start/end 는 텍스트 하나 안의 위치라서 배열을 한 키로 묶으면 뜻이 모호해진다
    hits: dict[str, list[Hit]]
    #: 전체 합산 개수. 키는 PiiKind
    counts: dict[str, int]


@dataclass(frozen=True)
class FieldsDetokenizeResult:
    #: 입력과 같은 키·같은 모양
    texts: dict[str, FieldValue]
    #: 필드별 미복원 토큰. 비어 있는 필드는 키가 없다.
    #: 배열 필드는 ``"tags[0]"`` 처럼 색인을 붙인다
    unresolved: dict[str, list[str]]
