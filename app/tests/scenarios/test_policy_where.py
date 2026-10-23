"""C11 ① 순수 계층 — C2 정책이 역할×등급×scope별 '올바른 WHERE'를 뱉는지 (DB 없음).

접근 통제 버그는 두 군데서 난다(docs/C11.md): **정책이 틀린 조건을 만들거나**, 그 조건이
**검색에 안 붙거나**. 여기서는 앞쪽 — C2 `Policy`/`build_where`가 실 `matrix.yaml`로
기대 조건을 만드는지만 본다. 뒤쪽(실 누출 0)은 ② 통합(pgvector)에서.

각 테스트는 docs/C11.md 시나리오 ID를 참조한다(추적성). 통합이 필요한 S-DEEP-1(원본 shares
재확인)·실누출은 여기 없다.
"""
import pytest

from app.policy.policy import GradeCond, Policy, build_where, default_matrix_path

UID = "user-123"


@pytest.fixture(scope="module")
def policy() -> Policy:
    """배포에 쓰는 실 매트릭스(번들 matrix.yaml 또는 POLICY_MATRIX_PATH)를 그대로 검증."""
    return Policy.load(default_matrix_path())


# --------------------------------------------------------------------------
# 정책 판정 (decision) — 매트릭스 칸이 의도대로인가
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("role", "grade", "expected"),
    [
        # user: 본인 personal 허용, 민감은 마스킹, 내부·기밀은 차단
        ("user", "public", ("allow", None)),
        ("user", "internal", ("block", None)),
        ("user", "personal", ("allow", "own")),
        ("user", "sensitive", ("mask", "own")),
        ("user", "confidential", ("block", None)),
        # mentor: 공유 범위에서만 personal/sensitive
        ("mentor", "personal", ("allow", "shared")),
        ("mentor", "sensitive", ("mask", "shared")),
        ("mentor", "confidential", ("block", None)),
        # operator: 전체 열람하되 personal/sensitive는 마스킹, 기밀은 차단
        ("operator", "internal", ("allow", None)),
        ("operator", "personal", ("mask", "all")),
        ("operator", "confidential", ("block", None)),
        # system: personal 전체 허용
        ("system", "personal", ("allow", "all")),
    ],
)
def test_decision_matches_matrix(policy, role, grade, expected):
    assert policy.decision(role, grade) == expected


def test_decision_unknown_role_or_grade_is_block(policy):
    # 정의 안 된 칸은 안전하게 block (fail-closed)
    assert policy.decision("ghost", "personal") == ("block", None)
    assert policy.decision("user", "ghost") == ("block", None)


# --------------------------------------------------------------------------
# S-GRADE — 검색 가능 등급에서 block 등급은 빠진다
# --------------------------------------------------------------------------

def test_retrieval_filter_excludes_blocked_grades(policy):
    """S-GRADE-1·2: user는 internal·confidential(block)이 필터에 안 들어온다 (allow/mask만)."""
    grades = {c.grade for c in policy.retrieval_filter("user", UID)}
    assert "internal" not in grades
    assert "confidential" not in grades
    assert {"public", "personal", "sensitive"} <= grades  # allow/mask 등급은 포함


def test_confidential_never_retrievable_for_any_role(policy):
    """어느 역할도 confidential을 검색 범위에 넣지 않는다."""
    for role in ("user", "mentor", "operator", "system"):
        grades = {c.grade for c in policy.retrieval_filter(role, UID)}
        assert "confidential" not in grades, role


# --------------------------------------------------------------------------
# S-NOFILTER — 필터 없는 경로 차단
# --------------------------------------------------------------------------

@pytest.mark.parametrize(("role", "uid"), [("", UID), ("user", ""), ("", "")])
def test_retrieval_filter_requires_role_and_user(policy, role, uid):
    """S-NOFILTER-1: role·user_id 없이는 필터를 만들 수 없다(검색 경로 자체가 막힌다)."""
    with pytest.raises(ValueError):
        policy.retrieval_filter(role, uid)


def test_empty_conditions_close_fail_closed():
    """허용 등급이 하나도 없으면 WHERE는 FALSE — 전부 차단(열리지 않는다)."""
    where, params = build_where([], user_id=UID)
    assert where == "FALSE"
    assert params == {}


# --------------------------------------------------------------------------
# S-OWN — 소유 경계: user personal은 owner_id 조건이 붙는다
# --------------------------------------------------------------------------

def test_own_scope_restricts_to_owner():
    """S-OWN-1·2: scope=own은 반드시 owner_id=:uid로 묶인다(타인 문서 구조적 배제)."""
    where, params = build_where([GradeCond("personal", "own")], user_id=UID)
    assert "owner_id = :uid" in where
    assert "grade = :g0" in where
    assert params["uid"] == UID


# --------------------------------------------------------------------------
# S-SHARE — 공유 경계: mentor shared는 만료 전 공유 원소만
# --------------------------------------------------------------------------

def test_shared_scope_checks_user_and_expiry():
    """S-SHARE-1·2: scope=shared는 shared_with에 요청자가 있고 만료 전인 경우만."""
    where, params = build_where([GradeCond("personal", "shared")], user_id=UID)
    assert "jsonb_array_elements" in where
    assert "e->>'user_id' = :uid" in where
    assert "expires_at" in where and "now()" in where
    assert params["uid"] == UID


# --------------------------------------------------------------------------
# S-OP — 운영자 과권한: 전체 열람(scope=all)은 소유/공유 제약이 없다 (마스킹은 출력단 A1/A5)
# --------------------------------------------------------------------------

def test_all_scope_has_no_ownership_restriction():
    """S-OP-1: scope=all/None은 grade 조건만 — operator는 전체를 본다(원문 PII 가림은 A1)."""
    where, params = build_where([GradeCond("personal", "all")], user_id=UID)
    assert where == "grade = :g0"
    assert "owner_id" not in where
    assert "uid" not in params  # all이면 uid 바인딩조차 안 쓴다


# --------------------------------------------------------------------------
# 구조 불변식 — own/shared는 절대 '맨 grade 조건'만으로 끝나지 않는다
# --------------------------------------------------------------------------

@pytest.mark.parametrize("scope", ["own", "shared"])
def test_restricted_scopes_never_bare_grade(scope):
    """own·shared가 소유/공유 제약 없이 grade만 남으면 전면 노출 버그 → 반드시 추가 조건."""
    where, _ = build_where([GradeCond("personal", scope)], user_id=UID)
    assert where != "grade = :g0"
    assert ("owner_id" in where) or ("jsonb_array_elements" in where)


# --------------------------------------------------------------------------
# 인젝션 방지 — user_id는 바인딩만, SQL 문자열에 직접 박히지 않는다
# --------------------------------------------------------------------------

def test_user_id_is_bound_not_interpolated():
    """악의적 user_id가 WHERE 문자열에 리터럴로 들어가지 않고 파라미터로만 간다."""
    evil = "x' OR '1'='1"
    where, params = build_where([GradeCond("personal", "own")], user_id=evil)
    assert evil not in where          # 문자열 연결 아님
    assert params["uid"] == evil      # 바인딩으로만 전달
    assert ":uid" in where


def test_real_matrix_end_to_end_for_user(policy):
    """실 매트릭스로 user 전체 필터를 만들어 WHERE가 합쳐지는지(각 등급 OR 결합)."""
    conds = policy.retrieval_filter("user", UID)
    where, params = build_where(conds, user_id=UID)
    assert where != "FALSE"
    assert " OR " in where            # 복수 등급 결합
    assert params["uid"] == UID       # own/shared 등급이 있어 uid 바인딩 존재
