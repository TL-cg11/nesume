"""A7 1차 규칙 검사기 테스트."""

from __future__ import annotations

import pytest

from app.features.writing import MAX_SENTENCE_LEN, Suggestion, apply_suggestions, check
from app.features.writing.suggestions import OverlappingSuggestions


def ids(text: str) -> set[str]:
    return {s.rule_id for s in check(text)}


# ---------------------------------------------------------------- 잡아야 하는 것

@pytest.mark.parametrize(
    "text,rule_id",
    [
        ("김철수은 지원했습니다.", "WR_PARTICLE"),
        ("결과은 좋았습니다.", "WR_PARTICLE"),
        ("프로젝트가 진행되어집니다.", "WR_DOUBLE_PASSIVE"),
        ("그렇게 보여집니다.", "WR_DOUBLE_PASSIVE"),
        ("할수있습니다.", "WR_SPACING"),
        ("최선을 다했습니다.", "WR_CLICHE"),
        ("많은 것을 배웠습니다.", "WR_CLICHE"),
    ],
)
def test_detects(text: str, rule_id: str) -> None:
    assert rule_id in ids(text), f"놓침: {text}"


def test_long_sentence_is_flagged() -> None:
    long = "가" * (MAX_SENTENCE_LEN + 10) + "."
    assert "WR_LONG_SENTENCE" in ids(long)


def test_short_sentence_is_not_flagged() -> None:
    assert "WR_LONG_SENTENCE" not in ids("짧은 문장입니다.")


def test_last_sentence_without_period_is_checked() -> None:
    """마침표 없이 끝나는 마지막 문장도 길이를 본다."""
    assert "WR_LONG_SENTENCE" in ids("나" * (MAX_SENTENCE_LEN + 5))


# ---------------------------------------------------------------- 잡으면 안 되는 것

@pytest.mark.parametrize(
    "text",
    [
        "저는 백엔드 개발자로 지원합니다.",
        "제 나이 입니다.",
        "사과 농장에서 일했습니다.",
        "이 프로젝트가 가장 기억에 남습니다.",
        "응답시간을 40% 단축했습니다.",
        "팀원 네 명과 협업했습니다.",
        "Python 3.12 와 FastAPI 를 사용했습니다.",
    ],
)
def test_no_false_positives(text: str) -> None:
    """교정 오탐이 많으면 사용자가 제안 목록 전체를 안 봅니다."""
    found = check(text)
    assert found == [], f"오탐: {[(s.rule_id, s.original) for s in found]}"


@pytest.mark.xfail(reason="관형형 어미를 조사로 읽는다. 형태소 분석 없이는 못 고친다", strict=False)
def test_known_limitation_adnominal_ending() -> None:
    """'지은 보고서' 의 '지은'(짓다)을 '지+은' 으로 읽는다.

    A1 의 미탐 3건과 같은 방식으로, 지금 실패하는 테스트로 남겨 둔다.
    조사 제안은 medium 신뢰도라 사용자가 거절할 수 있다.
    """
    assert check("제가 지은 보고서입니다.") == []


def test_particle_suggestions_are_medium_confidence() -> None:
    (s,) = [x for x in check("김철수은 지원했습니다.") if x.rule_id == "WR_PARTICLE"]
    assert s.confidence == "medium"


def test_other_rules_are_high_confidence() -> None:
    for text in ("진행되어집니다.", "할수있습니다."):
        for s in check(text):
            assert s.confidence == "high", s.rule_id


# ---------------------------------------------------------------- 제안의 성질

def test_empty_text() -> None:
    assert check("") == []
    assert check("   ") == []


def test_suggestions_are_sorted_by_position() -> None:
    text = "최선을 다했습니다. 그리고 진행되어집니다."
    starts = [s.start for s in check(text)]
    assert starts == sorted(starts), "화면에서 글을 따라 내려가며 봅니다"


def test_offsets_point_at_the_original() -> None:
    """위치가 어긋나면 반영할 때 엉뚱한 자리가 바뀝니다."""
    text = "프로젝트가 진행되어집니다. 할수있습니다."
    for s in check(text):
        if s.original:
            assert text[s.start : s.end] == s.original, s.rule_id


def test_guidance_only_suggestions_have_no_replacement() -> None:
    """상투어·긴 문장은 안내만 합니다. 대안은 글쓴이만 알 수 있습니다."""
    for s in check("최선을 다했습니다."):
        if s.rule_id == "WR_CLICHE":
            assert s.suggested == ""
            assert s.is_replacement is False


def test_ids_are_stable() -> None:
    """같은 글을 다시 검사하면 같은 id 가 나와야 '거절했음'이 유지됩니다."""
    text = "김철수은 진행되어집니다."
    assert [s.id for s in check(text)] == [s.id for s in check(text)]


def test_ids_differ_for_different_places() -> None:
    found = check("결과은 좋았고 성과은 컸습니다.")
    assert len({s.id for s in found}) == len(found)


# ---------------------------------------------------------------- 수락·거절 반영

def test_apply_only_accepted() -> None:
    text = "김철수은 지원했습니다."
    found = check(text)
    target = next(s for s in found if s.rule_id == "WR_PARTICLE")

    assert apply_suggestions(text, found, [target.id]) == "김철수는 지원했습니다."
    assert apply_suggestions(text, found, []) == text, "수락 안 한 것은 그대로"


def test_apply_multiple_keeps_offsets_valid() -> None:
    """★ 뒤에서부터 반영해야 앞의 길이 변화가 뒤 위치를 깨뜨리지 않습니다."""
    text = "할수있습니다. 그리고 진행되어집니다."
    found = [s for s in check(text) if s.is_replacement]
    out = apply_suggestions(text, found, [s.id for s in found])

    assert "할 수 있습니다" in out
    assert "진행됩니다" in out


def test_apply_ignores_guidance_only() -> None:
    text = "최선을 다했습니다."
    found = check(text)
    assert apply_suggestions(text, found, [s.id for s in found]) == text


def test_overlapping_acceptance_raises() -> None:
    """조용히 하나를 버리면 사용자는 반영됐다고 믿습니다."""
    text = "0123456789"
    a = Suggestion("spacing", "R1", 0, 5, "01234", "X", "")
    b = Suggestion("spacing", "R2", 3, 8, "34567", "Y", "")

    with pytest.raises(OverlappingSuggestions):
        apply_suggestions(text, [a, b], [a.id, b.id])


def test_adjacent_non_overlapping_is_fine() -> None:
    text = "0123456789"
    a = Suggestion("spacing", "R1", 0, 5, "01234", "X", "")
    b = Suggestion("spacing", "R2", 5, 8, "567", "Y", "")
    assert apply_suggestions(text, [a, b], [a.id, b.id]) == "XY89"


def test_unknown_id_is_ignored() -> None:
    text = "김철수은 지원했습니다."
    assert apply_suggestions(text, check(text), ["존재하지않는id"]) == text
