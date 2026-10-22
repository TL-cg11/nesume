"""A11 — 공고에서 요건 키워드를 뽑는다. **LLM 없이.**

## 왜 규칙으로 뽑는가

1. **공고 본문을 모델에 보내지 않아도 된다.** 공고는 외부 untrusted 텍스트다(C5).
   키워드를 모델에게 뽑게 하면 공고 전문이 매번 프롬프트에 들어간다 — 인젝션 표면이
   공고 하나 길이만큼 열린다. 규칙으로 뽑으면 모델에 가는 것은 **낱말 몇 개**뿐이다.
2. 값이 들지 않고, 같은 공고에 항상 같은 결과가 나온다.
3. 어느 필드에서 나온 요건인지 근거를 댈 수 있다 — "우대 사항입니다" 라고 말할 수 있다.

## 두 갈래로 뽑는다

| 갈래 | 대상 | 방법 |
| --- | --- | --- |
| 구조화 필드 | `certificates` `computer_skills` `major` `preferred` | **구분자로 쪼갠다** |
| 줄글 | `job_content` `title` `job_name` | **사전으로 찾는다**(`vocab`) |

구조화 필드를 사전으로만 보면 **사전 밖 요건을 통째로 놓친다** — 서울시 공고의
`CERTIFICATE` 에는 "요양보호사", "지게차운전기능사" 처럼 사전에 없는 말이 수없이 들어온다.
반대로 줄글을 구분자로 쪼개면 "것", "수행" 같은 조각이 키워드가 된다.

## 들어오기 전에 거쳐야 하는 것 (`service.prepare_posting`)

    연락처 제거 → A1 mask → C5 preprocess_external_text → **여기**

순서는 `docs/C5.md` 가 정한 것이다. 그래서 이 모듈은 마스킹 기호(``***``)와 C5 중화 마커
(``⟦무력화된 지시⟧``)가 섞인 텍스트를 받는다 — **둘 다 키워드가 되면 안 된다.**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from app.features.matching import vocab
from app.features.matching.vocab import Term, squash

#: 요건의 무게. 필수와 우대를 섞으면 **우대 사항이 빠진 것이 필수처럼 보인다.**
IMPORTANCES = ("required", "preferred", "mentioned")

_IMPORTANCE_RANK = {name: i for i, name in enumerate(IMPORTANCES)}

#: 구조화 필드와 기본 무게. `preferred` 필드만 우대다.
_STRUCTURED_FIELDS: tuple[tuple[str, str], ...] = (
    ("certificates", "required"),
    ("computer_skills", "required"),
    ("major", "required"),
    ("preferred", "preferred"),
)

#: 줄글 필드. 사전으로만 본다.
_PROSE_FIELDS: tuple[str, ...] = ("title", "job_name", "job_content")

#: 구조화 필드를 쪼개는 구분자.
_SPLIT = re.compile(r"[,/·∙•;|\n\r\t]+|\s{2,}|및\s|또는\s")

#: 조각에서 떼어낼 앞뒤 기호.
_TRIM = " \t -–—*·:：()[]{}\"'「」『』<>"

#: 조각 하나의 길이 상한. 이보다 길면 요건 낱말이 아니라 문장이다.
MAX_FRAGMENT_LEN = 25

#: 조각 하나의 길이 하한. 한 글자는 무엇이든 오탐이다.
MIN_FRAGMENT_LEN = 2

#: 키워드가 될 수 없는 조각. "무관" 을 요건으로 내보내면 사용자가 채우려고 한다.
_STOP_FRAGMENTS = frozenset(
    squash(w)
    for w in (
        "무관", "해당없음", "해당 없음", "없음", "없슴", "기타", "기타사항",
        "우대", "우대사항", "필수", "자격", "자격증", "면허", "전공", "학력",
        "경력", "신입", "경력무관", "학력무관", "전공무관", "관련학과", "제한없음",
        "이상", "미만", "가능자", "가능", "소지자", "소지",
    )
)

#: 숫자 + 단위만 있는 조각. "1급", "2년" 은 요건 이름이 아니라 **앞 요건에 붙은 수식어**인데
#: 구분자로 쪼개면서 떨어져 나온다. 그대로 두면 "1급" 이 요건 한 줄로 올라간다.
_NUMBER_WITH_UNIT = re.compile(r"\d+\s*(급|종|년|개월|점|차|회|등급|레벨|명|주)$")

#: 조각 안에 이것이 있으면 버린다 — 마스킹된 PII와 C5 가 중화한 지시문이다.
_REJECT_MARKERS = ("***", "⟦")

#: 조각 자체에 이 말이 있으면 필수에서 우대로 내린다.
#: 서울시 `CERTIFICATE` 에 "운전면허 우대" 처럼 섞여 들어온다.
_DOWNGRADE = ("우대", "가점", "선호", "있으면")


@dataclass(frozen=True)
class Keyword:
    """공고가 요구하는 것 하나.

    ``term`` 이 있으면 사전 항목이라 별칭까지 대조한다. 없으면 공고에 쓰인 말
    그대로만 대조한다 — 사전 밖 요건이라 별칭을 모른다.
    """

    text: str
    importance: str
    category: str
    #: 어느 필드에서 나왔나. 사용자에게 근거로 보여준다
    fields: tuple[str, ...]
    term: Term | None = None
    #: **택일(OR) 묶음** 이름. 같은 묶음은 하나만 맞아도 충족이다.
    #:
    #: ★ 전공이 그렇다. ``MAJOR`` 에 "컴퓨터공학, 소프트웨어학과" 가 적혀 있으면
    #:   **둘 다 하라는 말이 아니라 둘 중 하나**다. 따로 세면 전공을 맞춘 지원자도
    #:   달성률이 절반으로 나온다 — 숫자가 틀리면 사용자가 엉뚱한 곳을 고친다.
    group: str | None = None

    def __post_init__(self) -> None:
        if self.importance not in IMPORTANCES:
            raise ValueError(f"importance 는 {IMPORTANCES} 중 하나여야 합니다: {self.importance!r}")

    @property
    def key(self) -> str:
        return self.term.key if self.term else squash(self.text)

    @property
    def forms(self) -> tuple[str, ...]:
        """대조에 쓸 모든 표기."""
        return self.term.all_forms if self.term else (self.text,)

    @property
    def is_required(self) -> bool:
        return self.importance == "required"

    @property
    def from_vocab(self) -> bool:
        return self.term is not None


@dataclass(frozen=True)
class PostingFields:
    """A11 이 공고에서 보는 것만 모은 좁은 뷰.

    ★ C4 의 ORM 모델(`app.models.posting.JobPosting`)을 import 하지 않는다.
      - A11 단위 테스트가 DB 드라이버 없이 돌아야 한다
      - C4 가 컬럼을 바꿀 때 A11 이 같이 깨지지 않아야 한다
      조회해서 이 모양으로 바꿔 넘기는 일은 호출자(라우터·C4 연결)가 한다.
    """

    title: str | None = None
    job_name: str | None = None
    job_content: str | None = None
    certificates: str | None = None
    preferred: str | None = None
    major: str | None = None
    computer_skills: str | None = None

    def texts(self) -> list[tuple[str, str]]:
        """(필드명, 값) 목록. 비어 있는 필드는 빼고 돌려준다."""
        out = []
        for name in (
            "title", "job_name", "job_content",
            "certificates", "preferred", "major", "computer_skills",
        ):
            value = getattr(self, name)
            if value and value.strip():
                out.append((name, value))
        return out


@dataclass
class _Collector:
    """같은 키의 키워드를 합친다. 무게는 더 높은 쪽, 필드는 모두 남긴다."""

    by_key: dict[str, Keyword] = field(default_factory=dict)

    def add(self, kw: Keyword) -> None:
        old = self.by_key.get(kw.key)
        if old is None:
            self.by_key[kw.key] = kw
            return

        # 무게는 더 높은 쪽을 쓴다 — 우대 필드에도 적혀 있다고 필수가 내려가면 안 된다
        importance = (
            kw.importance
            if _IMPORTANCE_RANK[kw.importance] < _IMPORTANCE_RANK[old.importance]
            else old.importance
        )
        fields = tuple(dict.fromkeys(old.fields + kw.fields))
        # 사전 항목이 있는 쪽을 남긴다. 별칭까지 대조할 수 있다
        base = old if old.term is not None else kw
        self.by_key[kw.key] = Keyword(
            text=base.text, importance=importance, category=base.category,
            fields=fields, term=base.term,
        )

    def result(self) -> list[Keyword]:
        out = [self._grouped(k) for k in self.by_key.values()]
        return sorted(
            out,
            key=lambda k: (_IMPORTANCE_RANK[k.importance], k.category, k.text.casefold()),
        )

    @staticmethod
    def _grouped(kw: Keyword) -> Keyword:
        """택일 묶음을 붙인다.

        `major` **에서만** 나온 요건끼리 한 묶음이다. 다른 필드에도 적혀 있으면
        택일이라고 볼 수 없어 묶지 않는다 (줄글에 "컴퓨터공학 전공자 필수" 처럼
        따로 강조된 경우).
        """
        if kw.fields == ("major",):
            return replace(kw, group="major")
        return kw


def _clean_fragment(raw: str) -> str | None:
    """구분자로 쪼갠 조각을 키워드 후보로 다듬는다. 후보가 아니면 None."""
    frag = raw.strip(_TRIM).strip()
    if not frag:
        return None
    if any(m in frag for m in _REJECT_MARKERS):
        return None  # 마스킹된 PII · C5 가 중화한 지시문
    if not (MIN_FRAGMENT_LEN <= len(frag) <= MAX_FRAGMENT_LEN):
        return None
    if squash(frag) in _STOP_FRAGMENTS:
        return None
    if not re.search(r"[가-힣A-Za-z]", frag):
        return None  # 숫자·기호만 (연도)
    if _NUMBER_WITH_UNIT.fullmatch(frag):
        return None  # "1급" — 앞 요건의 수식어가 떨어져 나온 것
    return frag


def _importance_of(fragment: str, default: str) -> str:
    if default == "required" and any(w in fragment for w in _DOWNGRADE):
        return "preferred"
    return default


def extract(posting: PostingFields) -> list[Keyword]:
    """공고에서 요건 키워드를 뽑는다.

    구조화 필드는 구분자로, 줄글은 사전으로 본다. 같은 요건이 여러 필드에 있으면
    하나로 합치고 **무게는 더 높은 쪽**을 쓴다.
    """
    collector = _Collector()

    for name, default_importance in _STRUCTURED_FIELDS:
        value = getattr(posting, name)
        if not value:
            continue
        for raw in _SPLIT.split(value):
            frag = _clean_fragment(raw)
            if frag is None:
                continue
            importance = _importance_of(frag, default_importance)

            # 조각 안에 사전 항목이 있으면 **그것만** 쓴다.
            # "AWS 경험자" → AWS, "엑셀 고급 활용" → 엑셀.
            # 둘을 같이 넣으면 같은 요건이 두 줄로 보이고 달성률이 두 번 깎인다.
            #
            # 대가: "운전면허 1종 대형" 의 "1종 대형" 처럼 **수식어가 떨어진다.**
            # 급수·등급은 어차피 사용자 글에서 대조할 수 없어 받아들인다.
            inner = vocab.scan(frag)
            if inner:
                for term in inner:
                    collector.add(Keyword(
                        text=term.canonical, importance=importance,
                        category=term.category, fields=(name,), term=term,
                    ))
                continue

            # 사전 밖 요건. 공고에 쓰인 말 그대로 둔다 —
            # 사전이 모르는 자격·전공이 훨씬 많다 ("요양보호사", "지게차운전기능사")
            collector.add(Keyword(
                text=frag, importance=importance, category="other", fields=(name,),
            ))

    for name in _PROSE_FIELDS:
        value = getattr(posting, name)
        if not value:
            continue
        default_importance = "mentioned"
        for term in vocab.scan(value):
            collector.add(Keyword(
                text=term.canonical, importance=default_importance,
                category=term.category, fields=(name,), term=term,
            ))

    return collector.result()
