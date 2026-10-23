"""A11 키워드 추출 — 구조화 필드는 쪼개고, 줄글은 사전으로 본다."""

from __future__ import annotations

import pytest

from app.features.matching.keywords import (
    MAX_FRAGMENT_LEN,
    Keyword,
    PostingFields,
    extract,
)

SEOUL = PostingFields(
    title="사무보조 (엑셀 활용)",
    job_name="사무원",
    job_content="문서 작성 및 자료 정리. 엑셀로 월별 집계를 작성합니다.",
    certificates="컴퓨터활용능력 2급, 운전면허 우대",
    computer_skills="엑셀, 한글, 파워포인트",
    major="경영학, 회계학",
    preferred="사무 경험자, 요양보호사",
)


def by_text(posting: PostingFields) -> dict[str, Keyword]:
    return {k.text: k for k in extract(posting)}


# ---------------------------------------------------------------- 두 갈래

def test_structured_fields_are_split_on_delimiters() -> None:
    got = by_text(PostingFields(computer_skills="엑셀, 한글, 파워포인트"))
    assert {"엑셀", "한글", "파워포인트"} <= set(got)


def test_dictionary_free_requirements_survive_as_written() -> None:
    """★ 사전 밖 자격·전공이 훨씬 많다. 사전으로만 보면 통째로 놓친다."""
    got = by_text(PostingFields(certificates="요양보호사, 지게차운전기능사"))
    assert {"요양보호사", "지게차운전기능사"} <= set(got)


def test_prose_is_read_with_the_dictionary_only() -> None:
    """줄글을 구분자로 쪼개면 "것"·"수행" 같은 조각이 요건이 된다."""
    got = by_text(PostingFields(job_content="Python 으로 데이터를 정리하는 일을 합니다."))
    assert set(got) == {"Python"}


# ---------------------------------------------------------------- 무게

def test_preferred_field_is_not_required() -> None:
    """★ 섞으면 **우대 사항이 빠진 것이 필수처럼 보인다.**"""
    got = by_text(SEOUL)
    assert got["엑셀"].importance == "required"
    assert got["요양보호사"].importance == "preferred"


def test_fragment_saying_우대_is_downgraded() -> None:
    """서울시 CERTIFICATE 에는 "운전면허 우대" 처럼 섞여 들어온다."""
    got = by_text(PostingFields(certificates="정보처리기사, 운전면허 우대"))
    assert got["정보처리기사"].importance == "required"
    assert got["운전면허"].importance == "preferred"


def test_prose_mention_is_only_mentioned() -> None:
    got = by_text(PostingFields(job_content="Docker 를 씁니다"))
    assert got["Docker"].importance == "mentioned"


def test_same_requirement_in_two_fields_keeps_the_heavier_weight() -> None:
    got = by_text(PostingFields(computer_skills="엑셀", job_content="엑셀로 집계합니다"))
    assert got["엑셀"].importance == "required", "줄글에도 있다고 필수가 내려가면 안 된다"
    assert set(got["엑셀"].fields) == {"computer_skills", "job_content"}


# ---------------------------------------------------------------- 조각 손질

def test_masked_pii_never_becomes_a_keyword() -> None:
    """★ 공고 본문에 담당자 연락처가 섞여 들어온다. A1 이 가린 자리가 요건이 되면 안 된다."""
    got = by_text(PostingFields(certificates="정보처리기사, ***-****-****"))
    assert set(got) == {"정보처리기사"}


def test_neutralized_instruction_never_becomes_a_keyword() -> None:
    """C5 가 중화한 마커(⟦…⟧)가 요건으로 올라가면 화면에 그대로 보인다."""
    got = by_text(PostingFields(preferred="AWS 경험, ⟦무력화된 지시⟧하세요"))
    assert set(got) == {"AWS"}


@pytest.mark.parametrize("junk", ["무관", "해당없음", "기타", "제한없음", "경력무관"])
def test_stop_words_are_not_requirements(junk: str) -> None:
    """★ "무관" 을 요건으로 내보내면 사용자가 그것을 채우려고 한다."""
    assert by_text(PostingFields(certificates=f"{junk}, 정보처리기사")) .keys() == {"정보처리기사"}


def test_sentence_length_fragment_is_dropped() -> None:
    long_one = "가" * (MAX_FRAGMENT_LEN + 1)
    assert long_one not in by_text(PostingFields(preferred=f"{long_one}, AWS"))


def test_numbers_only_fragment_is_dropped() -> None:
    assert set(by_text(PostingFields(certificates="2024, 1급, 정보처리기사"))) == {"정보처리기사"}


def test_term_inside_a_fragment_replaces_the_fragment() -> None:
    """"AWS 경험자" 는 AWS 하나로 센다 — 두 줄로 보이면 달성률이 두 번 깎인다."""
    got = set(by_text(PostingFields(preferred="AWS 경험자")))
    assert got == {"AWS"}


# ---------------------------------------------------------------- 전체

def test_real_posting_shape() -> None:
    got = by_text(SEOUL)

    assert got["컴퓨터활용능력"].importance == "required"
    assert got["운전면허"].importance == "preferred"
    assert got["경영학"].category == "other", "사전 밖 전공"
    assert got["회계"].category == "domain", "회계학 → 사전의 회계"
    assert all(k.text for k in got.values())


def test_empty_posting_yields_nothing() -> None:
    assert extract(PostingFields()) == []


# ---------------------------------------------------------------- 알려진 한계


@pytest.mark.xfail(reason="사전 항목이 들어 있는 조각은 수식어가 떨어진다", strict=True)
def test_qualifier_next_to_a_dictionary_term_is_lost() -> None:
    """"운전면허 1종 대형" → 운전면허. "1종 대형" 이 떨어진다.

    급수·등급은 사용자 글에서 대조할 수 없어 받아들인 대가다. 화면에 원문 조각을
    함께 보여주려면 Keyword 에 표시용 원문을 더해야 한다.
    """
    got = by_text(PostingFields(certificates="운전면허 1종 대형"))
    assert "1종 대형" in str(got)
