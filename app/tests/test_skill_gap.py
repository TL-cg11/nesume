"""C10 학습 갭 정리 테스트. A11 결과 위의 얇은 계층 — DB·A11 import 불필요(순수)."""
from dataclasses import dataclass

from app.features.skill_gap.gap import (
    IMPORTANCE_RANK,
    LearningGap,
    _Match,
    from_coverage,
    learning_gaps,
)


def _m(key, status="missing", importance="required", fields=("job_content",)):
    return _Match(key=key, label=key.upper(), importance=importance, status=status, evidence_fields=fields)


def test_only_missing_is_a_learning_gap():
    # covered(이미 씀)·in_experience_only(경험엔 있으나 안 씀)는 학습 갭 아님
    matches = [
        _m("python", status="missing"),
        _m("aws", status="covered"),
        _m("docker", status="in_experience_only"),
    ]
    gaps = learning_gaps(matches)
    assert [g.key for g in gaps] == ["python"]


def test_required_before_preferred():
    matches = [
        _m("우대", importance="preferred"),
        _m("필수", importance="required"),
    ]
    gaps = learning_gaps(matches)
    assert [g.importance for g in gaps] == ["required", "preferred"]


def test_mentioned_excluded_by_default_but_optional():
    matches = [_m("스침", importance="mentioned")]
    assert learning_gaps(matches) == []                       # 기본 제외
    assert len(learning_gaps(matches, include_mentioned=True)) == 1  # 켜면 포함


def test_same_tier_sorted_by_label():
    matches = [_m("zebra"), _m("alpha")]
    gaps = learning_gaps(matches)
    assert [g.label for g in gaps] == ["ALPHA", "ZEBRA"]


def test_evidence_fields_preserved():
    gaps = learning_gaps([_m("k", fields=("certificates", "preferred"))])
    assert gaps[0].evidence_fields == ("certificates", "preferred")
    assert isinstance(gaps[0], LearningGap)


def test_importance_rank_order():
    assert IMPORTANCE_RANK["required"] < IMPORTANCE_RANK["preferred"] < IMPORTANCE_RANK["mentioned"]


def test_from_coverage_adapter_reads_a11_shape():
    # A11 coverage.Match 모양을 흉내낸 가짜 — import 없이 속성만 맞으면 된다
    @dataclass
    class FakeKeyword:
        text: str
        importance: str
        key: str
        fields: tuple

    @dataclass
    class FakeMatch:
        keyword: FakeKeyword
        status: str

    a11 = [
        FakeMatch(FakeKeyword("Python", "required", "python", ("job_content",)), "missing"),
        FakeMatch(FakeKeyword("AWS", "preferred", "aws", ("preferred",)), "covered"),
    ]
    flat = from_coverage(a11)
    assert [(m.key, m.importance, m.status) for m in flat] == [
        ("python", "required", "missing"),
        ("aws", "preferred", "covered"),
    ]
    # 어댑터 → 학습 갭까지 이어지는지
    gaps = learning_gaps(flat)
    assert [g.key for g in gaps] == ["python"]
