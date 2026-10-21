"""A4 분류 결과 스키마 단위 테스트.

★ 값 목록이 models/audit.py 의 DB CHECK 제약과 어긋나지 않는지 **직접 대조**한다.
  두 곳에 적힌 목록은 반드시 갈라진다 — 갈라지는 순간 테스트가 깨지게 해 둔다.

이 파일은 A 파트 테스트 중 유일하게 B 의 모델을 import 한다. 대조가 목적이라
어쩔 수 없다. `app.models.audit` → `app.db` 를 거치므로 DB_* 환경변수가 필요하다
(테스트 하네스에는 있다). DB 에 접속하지는 않고 테이블 메타데이터만 읽는다.
"""

from __future__ import annotations

import pytest

from app.guardrail import (
    CANARY_RULE_ID,
    DECISION_STAGES,
    DECISIONS,
    MAX_FLAG_LEN,
    MAX_RULE_ID_LEN,
    QUERY_TYPES,
    Finding,
    Verdict,
    allow,
    worse_decision,
)


# ---------------------------------------------------------------- DB 제약과 대조

def test_values_match_audit_log_constraints() -> None:
    """감사 로그 테이블의 허용값과 같아야 한다. 다르면 INSERT 가 실패한다."""
    from app.models.audit import DECISION_STAGES as DB_STAGES
    from app.models.audit import DECISIONS as DB_DECISIONS
    from app.models.audit import QUERY_TYPES as DB_QUERY_TYPES

    assert set(DECISIONS) == set(DB_DECISIONS)
    assert set(QUERY_TYPES) == set(DB_QUERY_TYPES)
    assert set(DECISION_STAGES) == set(DB_STAGES)


def test_column_lengths_match() -> None:
    from app.models.audit import AuditLog

    assert AuditLog.__table__.c.rule_id.type.length == MAX_RULE_ID_LEN
    assert AuditLog.__table__.c.flags.type.item_type.length == MAX_FLAG_LEN


def test_decision_has_exactly_three_values() -> None:
    """flag 는 판정이 아니라 표식이다. 네 번째 판정을 만들지 않는다."""
    assert len(DECISIONS) == 3
    assert "flag" not in DECISIONS


# ---------------------------------------------------------------- Finding 검증

def test_rule_id_too_long_is_rejected() -> None:
    """B11 은 finally 에서 로그를 쓴다. 거기서 INSERT 가 깨지면 기록이 통째로 사라진다."""
    with pytest.raises(ValueError, match="50자"):
        Finding("X" * (MAX_RULE_ID_LEN + 1), "warn")


def test_rule_id_at_limit_is_allowed() -> None:
    assert Finding("X" * MAX_RULE_ID_LEN, "warn").rule_id


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rule_id": "", "severity": "warn"},
        {"rule_id": "OK", "severity": "fatal"},
        {"rule_id": "OK", "severity": "warn", "count": 0},
    ],
)
def test_invalid_finding_is_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        Finding(**kwargs)


# ---------------------------------------------------------------- Verdict 파생값

def test_representative_rule_id_is_the_heaviest() -> None:
    """로그 컬럼이 하나라 여럿 걸렸을 때 무엇을 남길지 정해야 한다."""
    v = Verdict(
        decision="block",
        stage="output_guard",
        findings=(
            Finding("PII_PHONE", "warn", 2),
            Finding("LEAK_CANARY", "critical"),
            Finding("OUT_UNKNOWN_TOKEN", "info"),
        ),
    )
    assert v.rule_id == "LEAK_CANARY"
    assert v.flags == ["PII_PHONE", "LEAK_CANARY", "OUT_UNKNOWN_TOKEN"], "순서는 걸린 순서"


def test_representative_rule_id_breaks_tie_by_order() -> None:
    v = Verdict(
        decision="block",
        stage="output_guard",
        findings=(Finding("A", "critical"), Finding("B", "critical")),
    )
    assert v.rule_id == "A", "동률이면 먼저 걸린 것"


def test_flags_deduplicate_but_keep_order() -> None:
    v = Verdict(
        decision="mask",
        stage="output_guard",
        findings=(Finding("B", "warn"), Finding("A", "warn"), Finding("B", "info")),
    )
    assert v.flags == ["B", "A"]


def test_canary_hit_is_derived() -> None:
    v = Verdict(decision="block", stage="output_guard", findings=(Finding(CANARY_RULE_ID, "critical"),))
    assert v.canary_hit is True
    assert allow("classifier").canary_hit is False


def test_empty_verdict_has_no_rule_id() -> None:
    v = allow("classifier", query_type="normal")
    assert v.rule_id is None
    assert v.flags == []
    assert v.ok is True


# ---------------------------------------------------------------- 유효성

@pytest.mark.parametrize(
    "kwargs",
    [
        {"decision": "flag", "stage": "classifier"},
        {"decision": "allow", "stage": "llm"},
        {"decision": "allow", "stage": "classifier", "query_type": "weird"},
    ],
)
def test_invalid_verdict_is_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        Verdict(**kwargs)


# ---------------------------------------------------------------- 합치기

def test_merge_takes_the_heavier_decision() -> None:
    classifier = Verdict("mask", "classifier", (Finding("SENSITIVE", "warn"),), query_type="sensitive")
    output = Verdict("block", "output_guard", (Finding("LEAK_CANARY", "critical"),))

    merged = classifier.merge(output)
    assert merged.decision == "block"
    assert merged.stage == "output_guard", "어디서 막혔는지가 로그의 쓸모다"
    assert merged.query_type == "sensitive", "분류 단계가 정한 값을 유지한다"
    assert merged.flags == ["SENSITIVE", "LEAK_CANARY"]


def test_merge_keeps_earlier_stage_on_tie() -> None:
    """동률이면 파이프라인 앞쪽이 원인이다."""
    a = Verdict("mask", "classifier")
    b = Verdict("mask", "output_guard")
    assert a.merge(b).stage == "classifier"


def test_merge_sums_counts_for_the_same_rule() -> None:
    a = Verdict("mask", "classifier", (Finding("PII_PHONE", "info", 1),))
    b = Verdict("mask", "output_guard", (Finding("PII_PHONE", "warn", 2),))

    merged = a.merge(b)
    (finding,) = merged.findings
    assert finding.count == 3
    assert finding.severity == "warn", "무거운 심각도를 남긴다"


def test_merge_of_allows_stays_allow() -> None:
    merged = allow("classifier", query_type="normal").merge(allow("retriever"))
    assert merged.decision == "allow"
    assert merged.query_type == "normal"


def test_worse_decision_order() -> None:
    assert worse_decision("allow", "mask") == "mask"
    assert worse_decision("mask", "block") == "block"
    assert worse_decision("block", "allow") == "block"


# ---------------------------------------------------------------- 감사 로그 필드

def test_audit_fields_match_column_names() -> None:
    """B11 이 ** 로 펼쳐 쓴다. 키 이름이 컬럼과 같아야 한다."""
    from app.models.audit import AuditLog

    v = Verdict("block", "output_guard", (Finding("LEAK_CANARY", "critical"),), query_type="exfiltration")
    fields = v.to_audit_fields()

    columns = set(AuditLog.__table__.c.keys())
    assert set(fields) <= columns, f"컬럼에 없는 키: {set(fields) - columns}"


def test_audit_fields_content() -> None:
    v = Verdict(
        "mask",
        "output_guard",
        (Finding("PII_PHONE", "warn", 2), Finding("PII_EMAIL", "warn")),
        query_type="normal",
    )
    assert v.to_audit_fields() == {
        "decision": "mask",
        "decision_stage": "output_guard",
        "query_type": "normal",
        "flags": ["PII_PHONE", "PII_EMAIL"],
        "rule_id": "PII_PHONE",
        "canary_hit": False,
    }


# ---------------------------------------------------------------- A5 연동

def test_output_guard_produces_a_valid_verdict() -> None:
    from app.guardrail import check_output

    result = check_output("연락처 010-1234-5678 입니다")
    v = result.verdict

    assert v.stage == "output_guard"
    assert v.decision == "mask"
    assert v.rule_id == "PII_PHONE"
    assert result.flags == v.flags
    assert result.canary_hit is False


def test_output_guard_rule_ids_fit_the_column() -> None:
    """A5 가 만드는 rule_id 가 전부 50자 안에 들어가는지 본다."""
    from app.guardrail.output_guard import _SECRET_PATTERNS

    for name, _ in _SECRET_PATTERNS:
        assert len(f"LEAK_SECRET.{name}") <= MAX_RULE_ID_LEN
