"""A11 — 공고 요건과 사용자 글을 대조한다.

## 세 갈래로 나누는 것이 핵심이다

| 상태 | 뜻 | 사용자가 할 일 |
| --- | --- | --- |
| `covered` | 자소서 본문에 썼다 | 없음 |
| **`in_experience_only`** | **경험 데이터엔 있는데 자소서에 안 썼다** | **지금 바로 쓸 수 있다** |
| `missing` | 아무 데도 없다 | 해당 경험이 있는지부터 확인 |

★ 가운데 칸이 A11 이 주는 값의 대부분이다. "빠진 요건" 만 보여주면 사용자는
  **없는 경험을 지어내는 쪽**으로 간다. "이미 가진 것을 안 썼다" 는 지어낼 필요가 없다.

## 비율을 믿을 수 있는지도 함께 돌려준다

키워드가 2개뿐인 공고에서 "달성률 50%" 는 아무 뜻이 없다. `rate_reliable` 로 알린다.
숫자만 내보내면 **사용자가 그 숫자를 목표로 삼는다.**

## 복원하지 않는다

사용자 글은 PII 토큰화 상태로 저장된다(B7). 대조에 원문 PII 가 필요 없으므로
``detokenize`` 를 부르지 않는다 — 토큰(``[[PHONE_1]]``)은 어떤 요건과도 맞지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.features.matching import vocab
from app.features.matching.keywords import Keyword
from app.features.matching.vocab import found_in

#: 대조 결과. 순서가 곧 사용자에게 보여주는 순서다.
STATUSES = ("covered", "in_experience_only", "missing")

#: 이 개수보다 적으면 비율을 믿을 수 없다고 알린다.
MIN_KEYWORDS_FOR_RATE = 3


@dataclass(frozen=True)
class ExperienceRef:
    """경험 하나에서 대조에 쓰는 것만 모은 뷰.

    ``app.models.experience.Experience`` 를 import 하지 않는 이유는
    `keywords.PostingFields` 와 같다 — DB 없이 테스트하고, B 가 컬럼을 바꿀 때
    같이 깨지지 않기 위해서다.
    """

    label: str
    #: role · outcome · detail 을 이어 붙인 줄글
    text: str = ""
    #: tech_stack · tags — 구조화되어 있어 그대로 믿을 수 있다
    terms: tuple[str, ...] = ()

    def haystack(self) -> str:
        return " ".join((self.text, *self.terms))


@dataclass(frozen=True)
class UserEvidence:
    """사용자 쪽 근거. 자소서 본문과 경험 목록을 **구분해서** 들고 있다.

    구분하지 않으면 `in_experience_only` 를 만들 수 없다.
    """

    resume_text: str = ""
    experiences: tuple[ExperienceRef, ...] = ()


@dataclass(frozen=True)
class Match:
    keyword: Keyword
    status: str
    #: 근거가 된 경험 이름. `covered` 여도 경험에 있으면 함께 담는다
    experiences: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status 는 {STATUSES} 중 하나여야 합니다: {self.status!r}")


@dataclass(frozen=True)
class CoverageReport:
    matches: tuple[Match, ...]

    def of_status(self, status: str) -> tuple[Match, ...]:
        return tuple(m for m in self.matches if m.status == status)

    def counts(self) -> dict[str, int]:
        return {s: len(self.of_status(s)) for s in STATUSES}

    @property
    def required(self) -> tuple[Match, ...]:
        return tuple(m for m in self.matches if m.keyword.is_required)

    @property
    def required_units(self) -> tuple[tuple[Match, ...], ...]:
        """필수 요건을 **셀 단위로** 묶는다.

        택일 묶음(`Keyword.group`)은 하나로 센다 — 전공 "컴퓨터공학, 소프트웨어학과" 는
        둘 중 하나만 맞으면 충족이다.
        """
        groups: dict[str, list[Match]] = {}
        units: list[tuple[Match, ...]] = []
        for m in self.required:
            if m.keyword.group:
                groups.setdefault(m.keyword.group, []).append(m)
            else:
                units.append((m,))
        units.extend(tuple(v) for v in groups.values())
        return tuple(units)

    @property
    def required_rate(self) -> float | None:
        """필수 요건 중 **자소서에 쓴** 비율. 필수 요건이 없으면 None.

        ★ `in_experience_only` 는 센 것에 넣지 않는다. 자소서에 안 쓰면 읽는 사람은
          모른다 — 가지고 있다는 것과 전달했다는 것은 다르다.
        """
        units = self.required_units
        if not units:
            return None
        covered = sum(1 for unit in units if any(m.status == "covered" for m in unit))
        return covered / len(units)

    @property
    def rate_reliable(self) -> bool:
        """비율을 믿을 만한가. 키워드가 적으면 비율이 요동친다."""
        return len(self.matches) >= MIN_KEYWORDS_FOR_RATE

    @property
    def writable_now(self) -> tuple[Match, ...]:
        """경험엔 있는데 자소서에 안 쓴 것 — 지어내지 않고 채울 수 있는 것."""
        return self.of_status("in_experience_only")


def _hit(keyword: Keyword, text: str, vocab_keys: frozenset[str]) -> bool:
    """키워드가 이 텍스트에 있는가.

    사전 항목은 미리 구한 ``vocab_keys`` 로 본다 — 긴 별칭 우선·자리 덮기가
    적용된 결과여서 "자바스크립트" 를 "자바" 로 세지 않는다 (`vocab.matched_keys`).
    사전 밖 키워드는 쓰인 말 그대로 찾는다.
    """
    if keyword.term is not None:
        return keyword.term.key in vocab_keys
    return found_in(keyword.text, text)


def compare(keywords: tuple[Keyword, ...] | list[Keyword], evidence: UserEvidence) -> CoverageReport:
    """요건 하나하나를 자소서·경험과 대조한다."""
    resume_keys = vocab.matched_keys(evidence.resume_text)

    exp_hay = [(e.label, e.haystack()) for e in evidence.experiences]
    exp_keys = [(label, vocab.matched_keys(hay), hay) for label, hay in exp_hay]

    matches: list[Match] = []
    for kw in keywords:
        in_resume = _hit(kw, evidence.resume_text, resume_keys)
        found_exp = tuple(
            label for label, keys, hay in exp_keys if _hit(kw, hay, keys)
        )

        if in_resume:
            status = "covered"
        elif found_exp:
            status = "in_experience_only"
        else:
            status = "missing"

        matches.append(Match(keyword=kw, status=status, experiences=found_exp))

    # 보여주는 순서: 바로 쓸 수 있는 것 → 빠진 것 → 이미 쓴 것.
    # 사용자가 할 일이 있는 것을 위에 둔다
    order = {"in_experience_only": 0, "missing": 1, "covered": 2}
    matches.sort(key=lambda m: (order[m.status], not m.keyword.is_required, m.keyword.text.casefold()))
    return CoverageReport(matches=tuple(matches))
