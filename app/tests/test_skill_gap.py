"""C10 역량 갭 계산 테스트. DB·A11 불필요(순수)."""
from app.features.skill_gap.gap import (
    ESSENTIAL_WEIGHT,
    PREFERRED_WEIGHT,
    GapItem,
    RequiredCompetency,
    compute_gap,
    importance,
)


def _req(key, essential=True, freq=1):
    return RequiredCompetency(key=key, label=key.upper(), essential=essential, frequency=freq)


def test_gap_is_required_minus_held():
    required = [_req("python"), _req("aws"), _req("docker")]
    gaps = compute_gap(required, held_keys={"python"})
    keys = {g.key for g in gaps}
    assert keys == {"aws", "docker"}  # 보유한 python 제외


def test_empty_when_all_held():
    required = [_req("python"), _req("sql")]
    assert compute_gap(required, held_keys={"python", "sql"}) == []


def test_essential_always_outranks_preferred():
    # 빈도 높은 우대(5)여도 빈도 낮은 필수(1)보다 뒤 — 필수 먼저(must-have 우선)
    required = [_req("우대역량", essential=False, freq=5), _req("필수역량", essential=True, freq=1)]
    gaps = compute_gap(required, held_keys=set())
    assert gaps[0].key == "필수역량"


def test_importance_formula():
    assert importance(_req("x", essential=True, freq=3)) == ESSENTIAL_WEIGHT * 3
    assert importance(_req("x", essential=False, freq=2)) == PREFERRED_WEIGHT * 2


def test_frequency_breaks_tie_within_same_tier():
    required = [_req("a", essential=True, freq=1), _req("b", essential=True, freq=4)]
    gaps = compute_gap(required, held_keys=set())
    assert [g.key for g in gaps] == ["b", "a"]  # 같은 필수면 빈도 높은 b 먼저


def test_evidence_preserved():
    required = [RequiredCompetency(key="k", label="K", essential=True, frequency=1, evidence="본문 3번째 줄")]
    gaps = compute_gap(required, held_keys=set())
    assert gaps[0].evidence == "본문 3번째 줄"
    assert isinstance(gaps[0], GapItem)
