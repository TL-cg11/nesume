"""C2 정책 로더 단위 테스트. 실행: python test_policy.py -v

등급 값은 B2 `Grade` enum과 동일한 영문(public/internal/personal/sensitive/confidential).
"""

import os
import unittest

from policy import Policy, build_where, GradeCond

MATRIX = os.path.join(os.path.dirname(__file__), "matrix.yaml")


class TestDecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Policy.load(MATRIX)

    def test_user_own_personal(self):
        self.assertEqual(self.p.decision("user", "personal"), ("allow", "own"))

    def test_user_sensitive_mask(self):
        self.assertEqual(self.p.decision("user", "sensitive"), ("mask", "own"))

    def test_user_confidential_block(self):
        self.assertEqual(self.p.decision("user", "confidential"), ("block", None))

    def test_user_internal_block(self):
        self.assertEqual(self.p.decision("user", "internal"), ("block", None))

    def test_operator_internal_allow(self):
        self.assertEqual(self.p.decision("operator", "internal"), ("allow", None))

    def test_unknown_role_blocks(self):
        self.assertEqual(self.p.decision("hacker", "public"), ("block", None))

    def test_unknown_grade_blocks(self):
        self.assertEqual(self.p.decision("user", "topsecret"), ("block", None))


class TestRetrievalFilter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Policy.load(MATRIX)

    def test_user_grades(self):
        conds = self.p.retrieval_filter("user", "userA")
        grades = {c.grade for c in conds}
        # public + personal + sensitive (internal·confidential 제외)
        self.assertEqual(grades, {"public", "personal", "sensitive"})
        self.assertNotIn("confidential", grades)
        self.assertNotIn("internal", grades)

    def test_mentor_scope_shared(self):
        conds = {c.grade: c.scope for c in self.p.retrieval_filter("mentor", "m1")}
        self.assertEqual(conds["personal"], "shared")
        self.assertEqual(conds["sensitive"], "shared")

    def test_operator_includes_internal(self):
        grades = {c.grade for c in self.p.retrieval_filter("operator", "op1")}
        self.assertEqual(grades, {"public", "internal", "personal", "sensitive"})  # confidential만 제외

    def test_role_and_user_required(self):
        with self.assertRaises(ValueError):
            self.p.retrieval_filter("user", "")
        with self.assertRaises(ValueError):
            self.p.retrieval_filter("", "u")

    def test_unknown_role_empty(self):
        self.assertEqual(self.p.retrieval_filter("hacker", "u"), [])


class TestBuildWhere(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Policy.load(MATRIX)

    def test_user_where_shape(self):
        conds = self.p.retrieval_filter("user", "userA")
        sql, params = build_where(conds, user_id="userA")
        # public(무조건) + personal/sensitive(본인 소유)
        self.assertIn("owner_id = :uid", sql)
        self.assertIn(" OR ", sql)
        # 바인딩만 — 실제 user_id 문자열이 SQL에 직접 안 박힘
        self.assertNotIn("userA", sql)
        self.assertEqual(params["uid"], "userA")

    def test_no_raw_grade_in_sql(self):
        conds = self.p.retrieval_filter("user", "userA")
        sql, _ = build_where(conds, user_id="userA")
        for g in ("public", "personal", "sensitive"):
            self.assertNotIn(g, sql)  # 등급도 바인딩 파라미터로

    def test_mentor_shared_jsonb(self):
        conds = self.p.retrieval_filter("mentor", "m1")
        sql, params = build_where(conds, user_id="m1")
        # B2 JSONB shared_with [{user_id, expires_at}] 을 푸는 EXISTS
        self.assertIn("jsonb_array_elements(shared_with)", sql)
        self.assertIn("e->>'user_id' = :uid", sql)
        self.assertIn("(e->>'expires_at')::timestamptz > now()", sql)
        self.assertNotIn("ANY(", sql)  # 옛 배열 방식 흔적 없음

    def test_empty_conds_false(self):
        sql, params = build_where([], user_id="u")
        self.assertEqual(sql, "FALSE")
        self.assertEqual(params, {})

    def test_unknown_scope_raises(self):
        with self.assertRaises(ValueError):
            build_where([GradeCond("personal", "weird")], user_id="u")


if __name__ == "__main__":
    unittest.main()
