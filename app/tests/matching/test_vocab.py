"""A11 사전 대조 — 한국어에 낱말 경계가 없어서 생기는 문제들."""

from __future__ import annotations

import pytest

from app.features.matching import vocab
from app.features.matching.vocab import found_in, matched_keys, scan, squash


def names(text: str) -> list[str]:
    return [t.canonical for t in scan(text)]


# ---------------------------------------------------------------- 표기 차이

@pytest.mark.parametrize(
    "text",
    ["Node.js 로 서버를 만들었습니다", "node js 기반", "노드JS 사용", "NODE.JS"],
)
def test_same_term_across_notations(text: str) -> None:
    """공고는 "노드JS", 자소서는 "Node.js" 라고 쓴다. 같은 것으로 봐야 한다."""
    assert "Node.js" in names(text)


def test_squash_removes_separators() -> None:
    assert squash("Node.js") == squash("node js") == squash("NODE-JS") == "nodejs"


def test_korean_particle_needs_no_morphology() -> None:
    """"Python을" 의 조사를 떼지 않아도 잡힌다 — 앞뒤가 ASCII 가 아니라서."""
    assert names("Python을 사용했습니다") == ["Python"]


# ---------------------------------------------------------------- 오탐

@pytest.mark.parametrize(
    ("text", "absent"),
    [
        ("google 에서 검색했습니다", "Go"),        # go ⊂ google
        ("HTML 과 CSS 를 배웠습니다", "고객응대"),  # cs ⊂ css
        ("MySQL 튜닝", "SQL"),                    # sql ⊂ mysql
        ("프로젝트 결과를 정리", "TypeScript"),     # ts ⊂ projects
    ],
)
def test_english_term_inside_another_word_is_not_a_hit(text: str, absent: str) -> None:
    assert absent not in names(text)


def test_mysql_is_its_own_term() -> None:
    assert "MySQL" in names("MySQL 튜닝")


def test_hangul_one_letter_alias_is_rejected_by_the_dictionary() -> None:
    """★ "뷰"(Vue)·"깃"(Git) 은 별칭이 될 수 없다 — "인터뷰"·"깃발" 안에서 걸린다.

    영문은 앞뒤 ASCII 검사로 막히지만 한글은 막히지 않는다. 그래서 사전을 만들 때
    한 글자 한글 별칭을 거부한다.
    """
    for term in vocab.TERMS:
        for form in term.all_forms:
            key = squash(form)
            if vocab._HANGUL.search(key):
                assert len(key) >= 2, f"{form!r} ({term.canonical}) 은 한 글자 한글 별칭"


def test_interview_is_not_vue() -> None:
    assert names("인터뷰를 리뷰했습니다") == []


# ---------------------------------------------------------------- 긴 별칭 우선

def test_longer_alias_wins_and_hides_the_shorter_one() -> None:
    """★ "자바스크립트" 를 쓴 글이 "자바" 도 쓴 것으로 집계되면 안 된다.

    사용자는 **안 쓴 기술을 썼다고** 듣는다. 자리를 덮어 막는다.
    """
    assert names("자바 스크립트로 작업했습니다") == ["JavaScript"]


def test_both_are_counted_when_both_are_written() -> None:
    got = names("JavaScript 와 Java 를 모두 썼습니다")
    assert "Java" in got
    assert "JavaScript" in got


# ---------------------------------------------------------------- 숫자 경계

@pytest.mark.parametrize(
    ("text", "expected"),
    [("Python3 로 작성", "Python"), ("Java8 기준", "Java"), ("Vue3 사용", "Vue")],
)
def test_version_digit_is_the_same_technology(text: str, expected: str) -> None:
    """★ 뒤에 숫자가 오면 버전 표기다. 거절하면 흔한 표기를 전부 놓친다."""
    assert expected in names(text)


def test_grade_digit_after_korean_term_is_fine() -> None:
    """"컴퓨터활용능력 1급" — 급수가 붙어도 자격증은 자격증이다."""
    assert "컴퓨터활용능력" in names("컴퓨터활용능력 1급 보유")


# ---------------------------------------------------------------- 보조 함수

def test_found_in_takes_the_raw_text() -> None:
    assert found_in("정보처리기사", "정보처리기사 취득")
    assert not found_in("정보처리기사", "자격증 없음")


def test_space_joined_terms_keep_their_boundaries() -> None:
    """★ 공백을 지워 대조하면 ``"Django Docker PostgreSQL"`` 이 한 낱말이 되어 **하나도**
    안 잡힌다. 경험의 `tech_stack` 배열을 이어 붙이면 바로 이 모양이 된다 —
    사용자는 쓴 기술을 전부 "없다" 고 듣는다.
    """
    got = names("Django Docker PostgreSQL")
    assert {"Django", "Docker", "PostgreSQL"} == set(got)


def test_alias_matches_both_spacings() -> None:
    """별칭을 띄어 쓴 형태로 적으면 붙여 쓴 형태까지 함께 맞는다."""
    assert names("자바 스크립트") == names("자바스크립트") == ["JavaScript"]


def test_spacing_tolerance_does_not_invent_a_gap() -> None:
    """★ "한글" 을 "한 글" 로 적으면 "작성한 글" 이 걸린다. 없는 공백은 만들지 않는다."""
    assert names("제가 작성한 글입니다") == []


def test_matched_keys_is_a_set_of_canonical_keys() -> None:
    assert matched_keys("Docker 와 도커") == {squash("Docker")}


# ---------------------------------------------------------------- 알려진 한계
#
# 지우지 않고 **실패하는 테스트로 남긴다.** 한계를 테스트에서 지우면 모르는 것과
# 구분이 안 된다 (A1 미탐 3건·A10 known_miss 와 같은 방식).


@pytest.mark.xfail(reason="두 글자 한글 별칭은 다른 낱말 안에서 걸린다 — 형태소 분석 필요", strict=True)
def test_two_letter_korean_term_inside_another_word() -> None:
    """"자영업" 안의 "영업" 이 걸린다.

    한 글자는 사전에서 막았지만 두 글자는 막을 수 없다 — 엑셀·회계·토익처럼
    두 글자 요건이 너무 많다. 막으면 사전이 쓸모없어진다.
    """
    assert names("자영업을 했습니다") == []


@pytest.mark.xfail(reason="한 글자 기술명(C·R)은 오탐이 많아 사전에 넣지 않았다", strict=True)
def test_bare_single_letter_language() -> None:
    """공고에 "C" 만 적혀 있으면 못 잡는다. "C언어" 로 적혀야 잡는다."""
    assert "C언어" in names("C 개발 경험")
