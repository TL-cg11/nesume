"""A14 말투 추출 — **무엇을 저장하지 않는가**가 먼저다."""

from __future__ import annotations

import pytest

from app.features.profile.extract import (
    LONG_SENTENCE_LEN,
    MIN_SOURCE_CHARS,
    TOP_N,
    NotEnoughText,
    TokenizedTextError,
    extract,
)

PARAGRAPH = (
    "2025년 교내 프로젝트에서 예약 지연 문제를 맡게 되었습니다. "
    "그래서 캐시를 도입했습니다. "
    "그 결과 응답시간을 40% 단축했습니다. "
    "또한 팀원들과 설계를 함께 검토했습니다.\n"
)
LONG_TEXT = PARAGRAPH * 10 + "하지만 배운 점도 많았습니다. 특히 측정 없이 고치면 안 된다는 것을 알았습니다."


def filler(n: int) -> str:
    """길이가 n 자 이상인 글을 만든다. 문장 하나가 19자다."""
    return "저는 맡은 일을 끝까지 했습니다. " * (n // 19 + 2)


# ---------------------------------------------------------------- 표본 조건

def test_short_text_is_refused_with_how_much_is_missing() -> None:
    """★ 표본이 적으면 말투가 아니라 **그 글의 우연**이다 (tasks.md A14)."""
    with pytest.raises(NotEnoughText) as exc:
        extract("짧습니다.")

    assert str(MIN_SOURCE_CHARS) in str(exc.value)
    assert "부족" in str(exc.value), "몇 자 더 필요한지 알려준다"


def test_exactly_the_minimum_is_enough() -> None:
    text = filler(MIN_SOURCE_CHARS)[:MIN_SOURCE_CHARS]
    assert extract(text).source_chars == MIN_SOURCE_CHARS


def test_tokenized_text_is_refused() -> None:
    """★ 토큰이 섞인 글로 문장 길이를 세면 실제와 다른 값이 나온다."""
    with pytest.raises(TokenizedTextError):
        extract(filler(1100) + "연락처는 [[PHONE_1]] 입니다.")


# ---------------------------------------------------------------- ★ 저장하지 않는 것

def test_content_words_never_enter_the_profile() -> None:
    """★ 자주 쓰는 "표현" 을 그대로 담으면 회사명·학교명·이름이 프로필로 새어 들어온다.

    프로필은 PII 가 아니라고 생각하고 만든 테이블이라, **거기서 PII 가 새면 아무도
    예상하지 못한다.** 그래서 화이트리스트 안에서만 센다.
    """
    text = ("저는 가나다주식회사에서 홍길동 팀장과 일했습니다. "
            "가나다주식회사의 서비스를 개선했습니다. ") * 20
    style = extract(text)

    stored = " ".join((*style.endings, *style.connectives))
    assert "가나다주식회사" not in stored
    assert "홍길동" not in stored
    assert "팀장" not in stored


def test_only_whitelisted_endings_are_counted() -> None:
    """사전 밖 종결은 **개수조차 세지 않는다** — 세면 그 값이 어딘가에 남는다."""
    text = "그는 집에 갔지라. " * 100           # 사전에 없는 종결
    assert extract(text).endings == ()


def test_at_most_top_n_terms_are_kept() -> None:
    """★ 많이 남길수록 **문체 지문**이 선명해진다."""
    style = extract(LONG_TEXT)
    assert len(style.endings) <= TOP_N
    assert len(style.connectives) <= TOP_N


# ---------------------------------------------------------------- 측정값

def test_extracts_the_frequent_endings() -> None:
    style = extract(LONG_TEXT)
    assert "했습니다" in style.endings


def test_extracts_the_frequent_connectives() -> None:
    style = extract(LONG_TEXT)
    assert "그래서" in style.connectives
    assert all(c in ("그래서", "또한", "그 결과", "하지만", "특히") for c in style.connectives)


def test_longer_endings_win_over_shorter_ones() -> None:
    """★ "했습니다" 가 "습니다" 보다 먼저 걸려야 한다.

    A1 PERSON·A3 질의 분류·A13 문체 판정에서 반복됐던 **규칙 우선순위** 문제다.
    """
    style = extract("예약 기능을 만들었습니다. " * 100)
    assert style.endings and style.endings[0] == "었습니다"
    assert "습니다" not in style.endings


def test_average_sentence_length() -> None:
    short, long_one = "가나다라마.", "가나다라마바사아자차가나다라마."   # 6자 · 16자
    assert (len(short), len(long_one)) == (6, 16)

    style = extract((short + long_one) * 100)
    assert style.avg_sentence_len == 11, "둘의 평균"


def test_long_sentence_ratio() -> None:
    long_one = "가" * (LONG_SENTENCE_LEN + 10) + ". "
    style = extract((long_one + "짧습니다. ") * 10)
    assert style.long_sentence_ratio == 50


def test_paragraph_average_counts_single_newlines() -> None:
    """★ 빈 줄만 문단으로 보면 **줄바꿈 하나로 나눈 글이 한 문단**으로 세어진다."""
    style = extract(LONG_TEXT)
    assert 3 <= style.paragraph_avg_sentences <= 5


def test_numeric_density() -> None:
    style = extract(LONG_TEXT)
    assert style.numeric_density > 0, "2025·40% 를 쓰는 습관이 잡힌다"

    no_numbers = extract("저는 맡은 일을 끝까지 했습니다. " * 60)
    assert no_numbers.numeric_density == 0


def test_sentence_count_is_reported() -> None:
    """표본이 얇은 프로필인지 사용자가 판단할 근거다."""
    assert extract(LONG_TEXT).sentence_count > 30
