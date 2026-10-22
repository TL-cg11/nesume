"""A13 세기·문체 — 기준을 B4 와 맞추는 것이 먼저다."""

from __future__ import annotations

import pytest

from app.features.style.counter import TokenizedTextError, count
from app.features.style.tone import TONE_NAMES, analyze, ending_tone

# ---------------------------------------------------------------- 세기

def test_counts_like_b4() -> None:
    """★ B 는 `char_count=len(body)` 로 센다 — 공백 포함, 원문 기준.

    기준이 다르면 A13 이 "맞습니다" 라고 한 글이 저장할 때 제한을 넘는다.
    """
    text = "안녕하세요. 저는 지원자입니다."
    assert count(text).total == len(text)


def test_without_spaces_is_only_a_reference() -> None:
    c = count("가 나 다")
    assert c.total == 5
    assert c.without_spaces == 3


def test_newlines_count() -> None:
    assert count("가\n나").total == 3


def test_over_by_and_fits() -> None:
    c = count("가" * 1010)
    assert c.over_by(1000) == 10
    assert c.fits(1000) is False
    assert c.fits(None) is True, "제한이 없으면 길이는 보지 않는다"
    assert c.over_by(None) == 0


def test_tokenized_text_is_rejected() -> None:
    """★ 저장된 본문은 PII 토큰화 상태다. 그걸 세면 저장될 글자 수와 다른 수가 나온다."""
    with pytest.raises(TokenizedTextError):
        count("연락처는 [[PHONE_1]] 입니다")


def test_tokenized_text_can_be_counted_on_purpose() -> None:
    """모델 응답처럼 이미 검증한 글은 그냥 센다."""
    assert count("[[PHONE_1]]", allow_tokens=True).total == 11


# ---------------------------------------------------------------- 문체

@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("최선을 다했습니다", "formal"),
        ("제 강점입니다", "formal"),
        ("가능합니까", "formal"),
        ("끝까지 해냈어요", "polite"),
        ("좋지요", "polite"),
        ("결과는 좋았다", "plain"),
        ("팀을 담당함", "nominal"),
        ("현장에 갔음", "nominal"),
    ],
)
def test_ending_tone(sentence: str, expected: str) -> None:
    assert ending_tone(sentence) == expected


def test_formal_wins_over_plain() -> None:
    """★ `입니다` 는 `다` 로 끝난다. 했다체 규칙이 먼저 보면 합니다체가 전부 했다체가 된다.

    A1·A3 에서 반복됐던 **규칙 우선순위** 문제다.
    """
    assert ending_tone("제 강점입니다") == "formal"
    assert ending_tone("했습니다") == "formal"


def test_unjudgeable_sentence_is_none() -> None:
    assert ending_tone("프로젝트 경험") is None
    assert ending_tone("") is None


def test_trailing_marks_do_not_hide_the_ending() -> None:
    assert ending_tone('최선을 다했습니다."') == "formal"
    assert ending_tone("해냈어요!") == "polite"


def test_detects_mixed_tone() -> None:
    """★ 맞춤법 검사(A7)로는 안 잡힌다 — 두 문장 모두 맞는 문장이다."""
    a = analyze("저는 책임감이 강합니다. 그래서 끝까지 해냈어요.")

    assert a.is_mixed is True
    assert a.counts["formal"] == 1
    assert a.counts["polite"] == 1


def test_single_tone_is_not_mixed() -> None:
    a = analyze("저는 책임감이 강합니다. 끝까지 해냈습니다.")
    assert a.is_mixed is False
    assert a.main == "formal"


def test_off_tone_points_at_the_sentences() -> None:
    a = analyze("강합니다. 해냈어요. 좋았다.")
    off = a.off_tone("formal")

    assert [s.text for s in off] == ["해냈어요.", "좋았다."]
    assert all(s.start < s.end for s in off)


def test_unjudged_sentences_are_excluded_from_the_ratio() -> None:
    """제목처럼 명사로 끝나는 줄을 섞인 것으로 세면 안 된다."""
    a = analyze("지원 동기\n저는 책임감이 강합니다.")
    assert a.is_mixed is False
    assert len(a.sentences) == 2
    assert len(a.judged) == 1


def test_tone_names_are_korean_for_the_screen() -> None:
    assert TONE_NAMES["formal"] == "합니다체"
    assert TONE_NAMES["polite"] == "해요체"
