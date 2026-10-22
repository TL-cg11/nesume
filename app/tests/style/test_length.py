"""A13 규칙 줄이기 — 줄이기는 삭제라서 환각보다 위험하다."""

from __future__ import annotations

import pytest

from app.features.style.length import (
    OverlappingTrims,
    StaleTrim,
    Trim,
    apply_trims,
    find_trims,
    savings,
)


def applied(text: str) -> str:
    trims = find_trims(text)
    return apply_trims(text, trims, {t.id for t in trims})


def rules(text: str) -> set[str]:
    return {t.rule_id for t in find_trims(text)}


# ---------------------------------------------------------------- 무손실

def test_collapses_repeated_spaces() -> None:
    assert applied("했고   그래서") == "했고 그래서"


def test_collapses_blank_lines() -> None:
    assert applied("가\n\n\n\n나") == "가\n\n나"


def test_single_space_is_left_alone() -> None:
    assert find_trims("했고 그래서") == []


# ---------------------------------------------------------------- 늘어진 표현

@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("맡게 되었습니다", "맡게 되었습니다"),          # '하게 되었습니다' 아님 — 안 건드린다
        ("담당하게 되었습니다", "담당했습니다"),
        ("협업에 대하여 배웠습니다", "협업에 대해 배웠습니다"),
        ("대화를 통하여 풀었습니다", "대화를 통해 풀었습니다"),
        ("그렇기 때문에 맡았습니다", "그래서 맡았습니다"),
        ("개선하였습니다", "개선했습니다"),
    ],
)
def test_verbose_phrases_shrink(before: str, after: str) -> None:
    assert applied(before) == after


def test_every_rule_only_shortens() -> None:
    """★ 길이 조정 기능이 글을 늘리면 안 된다. 모든 제안의 절약량은 양수다."""
    text = ("저는 개인적으로 매우 많은 일을 담당하게 되었습니다.  "
            "그렇기 때문에 협업에 대하여 배웠고 이것이 강점이라고 생각합니다.")
    for t in find_trims(text):
        assert t.saved > 0, t.rule_id
    assert len(applied(text)) < len(text)


# ---------------------------------------------------------------- 어감만 더하는 말

def test_filler_adverbs_are_medium_confidence() -> None:
    """어감을 잃으므로 수락은 사용자에게 맡긴다."""
    trims = [t for t in find_trims("매우 많은 경험") if t.rule_id == "ST_FILLER"]
    assert trims and all(t.confidence == "medium" for t in trims)


def test_subject_is_not_deleted_with_the_filler() -> None:
    """★ "저는 개인적으로" 에서 **주어까지 지우지 않는다.**

    주어를 말없이 없애면 글쓴이가 알아채기 어렵다.
    """
    assert applied("저는 개인적으로 노력했습니다") == "저는 노력했습니다"


def test_hedge_does_not_double_the_copula() -> None:
    """★ 실제로 났던 버그 — "강점이라고 생각합니다" 를 "강점이입니다" 로 만들었다."""
    assert applied("이것이 강점이라고 생각합니다") == "이것이 강점입니다"


def test_hedge_leaves_what_it_cannot_shorten_safely() -> None:
    """"중요하다고 생각합니다" 는 형태소 분석 없이 줄이면 문법이 깨진다. 건드리지 않는다."""
    assert applied("협업이 중요하다고 생각합니다") == "협업이 중요하다고 생각합니다"


def test_no_rule_deletes_a_whole_sentence() -> None:
    """★ 무엇이 덜 중요한지는 글쓴이만 안다. 문장을 통째로 지우는 규칙은 넣지 않았다."""
    text = "저는 성실합니다. 매우 노력했습니다. 결과가 좋았습니다."
    out = applied(text)
    assert out.count(".") == text.count("."), "문장 수가 줄지 않았다"


# ---------------------------------------------------------------- 적용

def test_savings_matches_the_real_result() -> None:
    text = "저는 개인적으로 매우 많은 일을 담당하게 되었습니다."
    trims = find_trims(text)
    out = apply_trims(text, trims, {t.id for t in trims})
    assert len(text) - len(out) == savings(trims)


def test_applies_from_the_back() -> None:
    """★ 앞에서부터 바꾸면 뒤 제안의 위치가 전부 밀린다 (A7 에서 같은 실수를 했다)."""
    text = "매우 큰 일을 담당하게 되었습니다. 매우 어려웠습니다."
    trims = find_trims(text)
    assert len(trims) >= 3
    assert apply_trims(text, trims, {t.id for t in trims}) == "큰 일을 담당했습니다. 어려웠습니다."


def test_only_accepted_trims_are_applied() -> None:
    text = "매우 큰 일을 담당하게 되었습니다."
    trims = find_trims(text)
    one = next(t for t in trims if t.rule_id == "ST_VERBOSE")
    assert apply_trims(text, trims, {one.id}) == "매우 큰 일을 담당했습니다."


def test_stale_trim_is_refused() -> None:
    """제안을 받은 뒤 글을 고쳤다. 그대로 적용하면 엉뚱한 자리가 지워진다."""
    trims = find_trims("매우 큰 일")
    with pytest.raises(StaleTrim):
        apply_trims("완전히 다른 글입니다", trims, {t.id for t in trims})


def test_overlapping_trims_are_refused() -> None:
    """조용히 하나를 버리면 사용자는 반영된 줄 안다."""
    a = Trim(rule_id="ST_A", start=0, end=5, original="가나다라마", replacement="가", reason="")
    b = Trim(rule_id="ST_B", start=3, end=6, original="라마바", replacement="라", reason="")
    with pytest.raises(OverlappingTrims):
        apply_trims("가나다라마바사", [a, b], {a.id, b.id})


def test_id_changes_when_the_text_changes() -> None:
    """내용 해시라서 같은 자리라도 원문이 다르면 다른 id 가 된다 (A7 과 같은 방식)."""
    a = Trim(rule_id="ST_A", start=0, end=2, original="매우", replacement="", reason="")
    b = Trim(rule_id="ST_A", start=0, end=2, original="정말", replacement="", reason="")
    assert a.id != b.id


def test_overlapping_matches_prefer_the_earlier_rule() -> None:
    """규칙 순서가 우선순위다 — 무손실 규칙을 앞에 두었다."""
    trims = find_trims("가  나")
    assert [t.rule_id for t in trims] == ["ST_SPACE"]
