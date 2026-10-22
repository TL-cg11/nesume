"""C2 정책 로더 테스트. DB 불필요(순수 로직). 등급 값은 B2 `Grade`(영문)."""
from pathlib import Path

import pytest

import app.policy.policy as policy_mod
from app.policy.policy import GradeCond, Policy, build_where, default_matrix_path

MATRIX = str(Path(policy_mod.__file__).parent / "matrix.yaml")


@pytest.fixture(scope="module")
def policy() -> Policy:
    return Policy.load(MATRIX)


# --- decision ---

def test_user_own_personal(policy):
    assert policy.decision("user", "personal") == ("allow", "own")


def test_user_sensitive_mask(policy):
    assert policy.decision("user", "sensitive") == ("mask", "own")


def test_user_confidential_block(policy):
    assert policy.decision("user", "confidential") == ("block", None)


def test_user_internal_block(policy):
    assert policy.decision("user", "internal") == ("block", None)


def test_operator_internal_allow(policy):
    assert policy.decision("operator", "internal") == ("allow", None)


def test_unknown_role_blocks(policy):
    assert policy.decision("hacker", "public") == ("block", None)


def test_unknown_grade_blocks(policy):
    assert policy.decision("user", "topsecret") == ("block", None)


# --- retrieval_filter ---

def test_user_grades(policy):
    grades = {c.grade for c in policy.retrieval_filter("user", "userA")}
    assert grades == {"public", "personal", "sensitive"}
    assert "confidential" not in grades and "internal" not in grades


def test_mentor_scope_shared(policy):
    conds = {c.grade: c.scope for c in policy.retrieval_filter("mentor", "m1")}
    assert conds["personal"] == "shared"
    assert conds["sensitive"] == "shared"


def test_operator_includes_internal(policy):
    grades = {c.grade for c in policy.retrieval_filter("operator", "op1")}
    assert grades == {"public", "internal", "personal", "sensitive"}  # confidential만 제외


def test_role_and_user_required(policy):
    with pytest.raises(ValueError):
        policy.retrieval_filter("user", "")
    with pytest.raises(ValueError):
        policy.retrieval_filter("", "u")


def test_unknown_role_empty(policy):
    assert policy.retrieval_filter("hacker", "u") == []


# --- build_where ---

def test_user_where_shape(policy):
    sql, params = build_where(policy.retrieval_filter("user", "userA"), user_id="userA")
    assert "owner_id = :uid" in sql
    assert " OR " in sql
    assert "userA" not in sql  # 바인딩만, 값 직접 안 박힘
    assert params["uid"] == "userA"


def test_no_raw_grade_in_sql(policy):
    sql, _ = build_where(policy.retrieval_filter("user", "userA"), user_id="userA")
    for g in ("public", "personal", "sensitive"):
        assert g not in sql  # 등급도 바인딩 파라미터로


def test_mentor_shared_jsonb(policy):
    sql, _ = build_where(policy.retrieval_filter("mentor", "m1"), user_id="m1")
    assert "jsonb_array_elements(shared_with)" in sql
    assert "e->>'user_id' = :uid" in sql
    assert "(e->>'expires_at')::timestamptz > now()" in sql
    assert "ANY(" not in sql  # 옛 배열 방식 흔적 없음


def test_empty_conds_false():
    sql, params = build_where([], user_id="u")
    assert sql == "FALSE"
    assert params == {}


def test_unknown_scope_raises():
    with pytest.raises(ValueError):
        build_where([GradeCond("personal", "weird")], user_id="u")


# --- default_matrix_path (env 우선, 번들 폴백) ---

def test_default_matrix_path_fallback(monkeypatch):
    monkeypatch.delenv("POLICY_MATRIX_PATH", raising=False)
    assert default_matrix_path().endswith("matrix.yaml")  # 번들 기본


def test_default_matrix_path_env_override(monkeypatch):
    monkeypatch.setenv("POLICY_MATRIX_PATH", "/official/matrix.yaml")
    assert default_matrix_path() == "/official/matrix.yaml"  # D2 공식본 경로로 교체 가능
