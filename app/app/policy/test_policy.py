"""C2 정책 로더 단위 테스트. 실행: python test_policy.py -v"""

import os
import unittest

from policy import Policy, build_where, GradeCond

MATRIX = os.path.join(os.path.dirname(__file__), "matrix.yaml")


class TestDecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Policy.load(MATRIX)

    def test_user_own_personal(self):
        self.assertEqual(self.p.decision("user", "개인"), ("allow", "own"))

    def test_user_sensitive_mask(self):
        self.assertEqual(self.p.decision("user", "민감"), ("mask", "own"))

    def test_user_confidential_block(self):
        self.assertEqual(self.p.decision("user", "기밀"), ("block", None))

    def test_user_internal_block(self):
        self.assertEqual(self.p.decision("user", "내부"), ("block", None))

    def test_operator_internal_allow(self):
        self.assertEqual(self.p.decision("operator", "내부"), ("allow", None))

    def test_unknown_role_blocks(self):
        self.assertEqual(self.p.decision("hacker", "공개"), ("block", None))

    def test_unknown_grade_blocks(self):
        self.assertEqual(self.p.decision("user", "초특급"), ("block", None))


class TestRetrievalFilter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Policy.load(MATRIX)

    def test_user_grades(self):
        conds = self.p.retrieval_filter("user", "userA")
        grades = {c.grade for c in conds}
        # 공개 + 개인 + 민감 (내부·기밀 제외)
        self.assertEqual(grades, {"공개", "개인", "민감"})
        self.assertNotIn("기밀", grades)
        self.assertNotIn("내부", grades)

    def test_mentor_scope_shared(self):
        conds = {c.grade: c.scope for c in self.p.retrieval_filter("mentor", "m1")}
        self.assertEqual(conds["개인"], "shared")
        self.assertEqual(conds["민감"], "shared")

    def test_operator_includes_internal(self):
        grades = {c.grade for c in self.p.retrieval_filter("operator", "op1")}
        self.assertEqual(grades, {"공개", "내부", "개인", "민감"})  # 기밀만 제외

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
        # 공개(무조건) + 개인/민감(본인 소유) 형태
        self.assertIn("owner_id = :uid", sql)
        self.assertIn(" OR ", sql)
        # 바인딩만 — 실제 user_id 문자열이 SQL에 직접 안 박힘
        self.assertNotIn("userA", sql)
        self.assertEqual(params["uid"], "userA")

    def test_no_raw_grade_in_sql(self):
        conds = self.p.retrieval_filter("user", "userA")
        sql, _ = build_where(conds, user_id="userA")
        for g in ("공개", "개인", "민감"):
            self.assertNotIn(g, sql)  # 등급도 바인딩 파라미터로

    def test_mentor_shared_clause(self):
        conds = self.p.retrieval_filter("mentor", "m1")
        sql, params = build_where(conds, user_id="m1")
        self.assertIn("ANY(shared_with)", sql)
        self.assertIn("expires_at > now()", sql)

    def test_empty_conds_false(self):
        sql, params = build_where([], user_id="u")
        self.assertEqual(sql, "FALSE")
        self.assertEqual(params, {})

    def test_unknown_scope_raises(self):
        with self.assertRaises(ValueError):
            build_where([GradeCond("개인", "weird")], user_id="u")


if __name__ == "__main__":
    unittest.main()
