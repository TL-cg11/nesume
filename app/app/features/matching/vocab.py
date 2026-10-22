"""A11 공용 용어 사전 — 공고와 사용자 글을 같은 말로 맞추기 위한 것.

공고는 "자바스크립트", 자소서는 "JavaScript" 라고 쓴다. 글자로 비교하면 둘은 다르고,
사용자는 **쓴 것을 안 썼다고** 듣는다. 그래서 별칭을 한곳에 모은다.

## 대조 방식 — `squash` 로 눌러서 비교한다

공백·점·하이픈·슬래시를 지우고 NFKC + casefold 한다.

    "Node.js" · "node js" · "노드 JS"  →  "nodejs"

★ **한 글자 용어(`C`, `R`, `Go` 의 일부 표기)는 넣지 않는다.** 한국어 문장에 섞인 한 글자는
  오탐이 너무 많다 — "C" 는 "C언어" 로만, "R" 은 넣지 않는다. 사전이 작아지는 것보다
  **쓴 적 없는 기술을 썼다고 말하는 것**이 나쁘다 (A5 과차단과 같은 판단).

★ **별칭은 띄어 쓴 형태로 적는다.** 패턴이 구분자를 0개 이상으로 보므로
  ``"자바 스크립트"`` 하나로 ``"자바스크립트"`` 까지 함께 맞는다. 반대로 붙여 쓴 형태만
  적으면 띄어 쓴 글을 놓친다. 단 **없는 공백을 만들지는 않는다** — ``"한글"`` 을
  ``"한 글"`` 로 적으면 ``"작성한 글"`` 이 걸린다.

★ 사전은 **공고를 설명하는 수단이지 정답이 아니다.** 사전 밖 용어는 구조화 필드를
  구분자로 쪼개 그대로 키워드가 된다 (`keywords.py`). 그래서 사전이 비어도 A11 은 돈다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: 낱말 안의 구분 문자. "Node.js" 와 "node js" 를 같게 본다.
_SEPARATORS = re.compile(r"[\s._\-/]+")

#: 별칭 안에서 구분 문자가 있어도/없어도 맞도록 하는 패턴 조각.
_SEP_CLASS = r"[\s._\-/]*"


def normalize(text: str) -> str:
    """NFKC + casefold. **공백은 지우지 않는다.**

    ★ 공백을 지우면 ``"Django Docker"`` 가 ``"djangodocker"`` 가 되어 **낱말 경계가
      사라진다.** 그러면 둘 다 다른 낱말의 일부로 보여 하나도 안 잡힌다 —
      경험의 `tech_stack` 배열을 이어 붙일 때 바로 이 모양이 된다.
    """
    return unicodedata.normalize("NFKC", text).casefold()


def squash(text: str) -> str:
    """구분 문자까지 지운 형태. **키를 만들 때만** 쓴다 (대조에는 쓰지 않는다)."""
    return _SEPARATORS.sub("", unicodedata.normalize("NFKC", text)).casefold()


def _is_ascii_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _pattern_for(alias: str) -> re.Pattern[str]:
    r"""별칭을 "구분자가 있어도 없어도 맞는" 정규식으로 바꾼다.

        "Node.js"  →  node[\s._\-/]*js      ← "node js" · "nodejs" 둘 다 맞음
        "자바 스크립트" →  자바[\s._\-/]*스크립트
    """
    parts = [re.escape(p) for p in _SEPARATORS.split(normalize(alias)) if p]
    return re.compile(_SEP_CLASS.join(parts))


def _boundary_ok(alias_squashed: str, hay: str, start: int, end: int) -> bool:
    """찾은 자리가 다른 낱말의 일부가 아닌가.

    ★ 검사는 **별칭 쪽 글자가 ASCII 영숫자인 면에만** 적용한다.

      - ``go`` 는 양쪽이 ASCII 라 ``google`` 안에서 거절된다
      - ``컴퓨터활용능력`` 은 끝이 한글이라 뒤가 숫자여도(``컴퓨터활용능력 1급``) 통과한다
      - 뒤는 **글자만** 거절한다. 숫자는 버전 표기라 같은 기술이다 (``Python3``)
    """
    if alias_squashed[0].isascii() and alias_squashed[0].isalnum():
        before = hay[start - 1] if start > 0 else ""
        if _is_ascii_alnum(before):
            return False
    if alias_squashed[-1].isascii() and alias_squashed[-1].isalnum():
        after = hay[end] if end < len(hay) else ""
        if after.isascii() and after.isalpha():
            return False
    return True


def _search(alias: str, hay: str, from_index: int = 0) -> tuple[int, int] | None:
    """정규화된 ``hay`` 에서 별칭이 **낱말로** 나오는 첫 자리. 없으면 None."""
    key = squash(alias)
    if not key:
        return None
    pattern = _pattern_for(alias)
    pos = from_index
    while True:
        m = pattern.search(hay, pos)
        if m is None:
            return None
        if _boundary_ok(key, hay, m.start(), m.end()):
            return m.start(), m.end()
        pos = m.start() + 1


def found_in(alias: str, text: str) -> bool:
    """별칭이 텍스트 안에 **낱말로** 있는가. ``text`` 는 원문 그대로 넘긴다.

    한국어는 ASCII 가 아니므로 ``"python을 사용"`` 의 ``python`` 은 그대로 잡힌다 —
    조사를 떼려고 형태소 분석을 하지 않아도 된다.
    """
    return _search(alias, normalize(text)) is not None


@dataclass(frozen=True)
class Term:
    """사전 한 항목. ``canonical`` 이 화면에 보이는 이름이다."""

    canonical: str
    aliases: tuple[str, ...]
    category: str

    @property
    def all_forms(self) -> tuple[str, ...]:
        return (self.canonical, *self.aliases)

    @property
    def key(self) -> str:
        return squash(self.canonical)


def _t(canonical: str, *aliases: str, category: str) -> Term:
    return Term(canonical=canonical, aliases=aliases, category=category)


#: 분류. 화면에서 묶어 보여주고, 빠진 요건에 맞는 질문 문구를 고르는 데 쓴다.
CATEGORIES = ("language", "framework", "data", "cloud", "tool", "office", "cert", "domain")

TERMS: tuple[Term, ...] = (
    # --- 언어 ---
    _t("Python", "파이썬", category="language"),
    _t("Java", "자바", category="language"),
    _t("JavaScript", "자바 스크립트", "JS", category="language"),
    _t("TypeScript", "타입 스크립트", "TS", category="language"),
    _t("C언어", "C 언어", category="language"),
    _t("C++", "씨플러스플러스", "CPP", category="language"),
    _t("C#", "씨샵", "CSharp", category="language"),
    _t("Kotlin", "코틀린", category="language"),
    _t("Swift", "스위프트", category="language"),
    _t("Go", "golang", "고랭", category="language"),
    _t("PHP", "피에이치피", category="language"),
    _t("SQL", "에스큐엘", category="language"),
    # --- 프레임워크·라이브러리 ---
    _t("Spring", "스프링", "Spring Boot", "스프링 부트", category="framework"),
    _t("Django", "장고", category="framework"),
    _t("FastAPI", "패스트API", category="framework"),
    _t("Flask", "플라스크", category="framework"),
    _t("React", "리액트", "React.js", category="framework"),
    _t("Vue", "Vue.js", "뷰JS", category="framework"),
    _t("Node.js", "노드JS", "노드", category="framework"),
    _t("Next.js", "넥스트JS", category="framework"),
    # --- 데이터 ---
    _t("PostgreSQL", "포스트그레SQL", "포스트그레스", "Postgres", category="data"),
    _t("MySQL", "마이에스큐엘", category="data"),
    _t("Oracle", "오라클", category="data"),
    _t("MongoDB", "몽고DB", "몽고디비", category="data"),
    _t("Redis", "레디스", category="data"),
    _t("Elasticsearch", "엘라스틱서치", category="data"),
    _t("Pandas", "판다스", category="data"),
    _t("머신러닝", "머신 러닝", "machine learning", "ML", category="data"),
    _t("딥러닝", "딥 러닝", "deep learning", category="data"),
    _t("데이터분석", "데이터 분석", "data analysis", category="data"),
    # --- 클라우드·인프라 ---
    _t("AWS", "아마존 웹 서비스", "Amazon Web Services", category="cloud"),
    _t("Azure", "애저", category="cloud"),
    _t("GCP", "구글 클라우드", "Google Cloud", category="cloud"),
    _t("Docker", "도커", category="cloud"),
    _t("Kubernetes", "쿠버네티스", "k8s", category="cloud"),
    _t("Linux", "리눅스", category="cloud"),
    _t("Terraform", "테라폼", category="cloud"),
    _t("CI/CD", "씨아이씨디", category="cloud"),
    # --- 도구 ---
    _t("Git", "GitHub", "깃허브", category="tool"),
    _t("Jira", "지라", category="tool"),
    _t("Figma", "피그마", category="tool"),
    _t("Jenkins", "젠킨스", category="tool"),
    # --- 사무 ---
    _t("엑셀", "Excel", "MS Excel", category="office"),
    _t("파워포인트", "PowerPoint", "PPT", category="office"),
    _t("한글", "아래아한글", "HWP", category="office"),
    _t("워드", "MS Word", category="office"),
    _t("컴퓨터활용능력", "컴활", category="office"),
    # --- 자격증 ---
    _t("정보처리기사", category="cert"),
    _t("정보처리산업기사", category="cert"),
    _t("SQLD", "SQL개발자", category="cert"),
    _t("ADsP", "데이터분석 준전문가", category="cert"),
    _t("토익", "TOEIC", category="cert"),
    _t("오픽", "OPIc", category="cert"),
    _t("운전면허", "자동차 운전면허", category="cert"),
    _t("사회복지사", category="cert"),
    _t("한국사능력검정", "한국사 능력검정시험", category="cert"),
    # --- 직무 역량 ---
    _t("고객응대", "고객 응대", "CS", "고객상담", category="domain"),
    _t("재고관리", "재고 관리", category="domain"),
    _t("회계", "경리", category="domain"),
    _t("마케팅", "marketing", category="domain"),
    _t("영업", "sales", category="domain"),
    _t("품질관리", "QA", "품질 관리", category="domain"),
    _t("프로젝트관리", "PM", "프로젝트 관리", category="domain"),
)


#: 한글 한 글자는 별칭이 될 수 없다. 아래 `_BY_ALIAS` 를 만들 때 검사한다.
_HANGUL = re.compile(r"[가-힣]")


#: 누른 별칭 → Term. 같은 별칭이 둘이면 사전을 고쳐야 하므로 바로 터뜨린다.
_BY_ALIAS: dict[str, Term] = {}
for _term in TERMS:
    for _form in _term.all_forms:
        _k = squash(_form)
        # ★ 한국어는 낱말 경계가 없다. 한 글자 한글 별칭은 다른 낱말 안에서 걸린다 —
        #   "뷰"(Vue)는 "인터뷰"·"리뷰" 에, "깃"(Git)은 "깃발" 에 걸린다.
        #   영문은 앞뒤 ASCII 영숫자 검사로 막히지만(`found_in`) 한글은 막히지 않는다.
        if len(_k) < 2 and _HANGUL.search(_k):
            raise ValueError(
                f"한글 한 글자는 별칭으로 쓸 수 없습니다: {_form!r} ({_term.canonical}) — "
                "다른 낱말 안에서 오탐이 납니다"
            )
        if _k in _BY_ALIAS and _BY_ALIAS[_k] is not _term:
            raise ValueError(
                f"사전에 같은 별칭이 둘 있습니다: {_form!r} — "
                f"{_BY_ALIAS[_k].canonical} vs {_term.canonical}"
            )
        _BY_ALIAS[_k] = _term

#: (별칭 원문, Term) 을 **긴 것부터**. "자바스크립트" 가 "자바" 보다 먼저 걸려야 한다.
_SCAN_ORDER: tuple[tuple[str, Term], ...] = tuple(
    sorted(
        ((form, term) for term in TERMS for form in term.all_forms),
        key=lambda ft: -len(squash(ft[0])),
    )
)


def lookup(fragment: str) -> Term | None:
    """조각이 사전의 어떤 항목인가. 정확히 같은 말일 때만 돌려준다."""
    return _BY_ALIAS.get(squash(fragment))


#: 이미 잡힌 자리를 덮어 두는 글자. ASCII 영숫자가 아니라 낱말 경계는 유지된다.
_TAKEN = "\x00"


def matched_keys(text: str) -> frozenset[str]:
    """텍스트에 나온 사전 항목의 키.

    ★ **긴 별칭부터 보고, 잡은 자리를 덮는다.** 한국어에는 낱말 경계가 없어
      ``"자바스크립트"`` 안에서 ``"자바"`` 가 걸린다. 덮지 않으면 JavaScript 를 쓴 글이
      Java 도 쓴 것으로 집계된다 — 사용자는 **안 쓴 기술을 썼다고** 듣는다.

      영문 사이 경계는 앞뒤 ASCII 검사로 막지만(``google`` 안의 ``go``), 한글은 그
      방법으로 막히지 않는다. 그래서 자리를 덮는 쪽으로 처리한다.
    """
    hay = normalize(text)
    hits: set[str] = set()

    for alias, term in _SCAN_ORDER:
        if term.key in hits:
            continue
        span = _search(alias, hay)
        if span is None:
            continue
        hits.add(term.key)
        lo, hi = span
        hay = hay[:lo] + _TAKEN * (hi - lo) + hay[hi:]

    return frozenset(hits)


def scan(text: str) -> list[Term]:
    """줄글에서 사전 항목을 찾는다. 사전에 적은 순서로 돌려준다.

    줄글은 구분자로 쪼갤 수 없어 사전으로만 찾는다 — 형태소 분석 없이 명사구를
    뽑으면 "것", "수행" 같은 조각이 키워드가 된다.
    """
    hits = matched_keys(text)
    return [t for t in TERMS if t.key in hits]
