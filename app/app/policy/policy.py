"""C2 — 공용 정책 로더.

`matrix.yaml`(역할×등급 매트릭스)을 읽어
  - 검색에 쓸 필터 조건(FilterSpec) → C6 retriever
  - 역할·등급 접근 판정(decision)      → A3 classifier
을 만든다. spec §6.3·§8.2.

검색 가능 등급 = decision이 allow 또는 mask (block은 제외).
mask 등급도 "검색은 되고 출력 때 A5가 가림"이라 필터엔 포함한다(C1 PoC와 동일).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

# 검색 결과에 들어올 수 있는 판정 (block 제외)
_RETRIEVABLE = {"allow", "mask"}

#: 번들 매트릭스(개발·테스트 기본). D2 공식본은 POLICY_MATRIX_PATH 환경변수로 교체.
_BUNDLED_MATRIX = Path(__file__).parent / "matrix.yaml"


def default_matrix_path() -> str:
    """정책 매트릭스 경로. 환경변수 `POLICY_MATRIX_PATH` 우선, 없으면 번들 `matrix.yaml`.

    D2 공식 매트릭스가 나오면 배포에서 `POLICY_MATRIX_PATH`만 그 위치로 세팅하면 된다
    (코드 변경 없이 교체). 공용 `config.py`를 건드리지 않으려고 env로 둔다.
    """
    return os.environ.get("POLICY_MATRIX_PATH") or str(_BUNDLED_MATRIX)


@dataclass(frozen=True)
class GradeCond:
    grade: str
    scope: str | None  # own / shared / all / None


class Policy:
    def __init__(self, roles: dict):
        self._roles = roles

    @classmethod
    def load(cls, path: str) -> Policy:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(roles=data["roles"])

    def decision(self, role: str, grade: str) -> tuple[str, str | None]:
        """역할·등급 판정. 정의되지 않은 칸은 안전하게 block."""
        cell = self._roles.get(role, {}).get(grade)
        if not cell:
            return ("block", None)
        return (cell["decision"], cell.get("scope"))

    def retrieval_filter(self, role: str, user_id: str) -> list[GradeCond]:
        """검색에 적용할 등급·scope 조건 목록. role·user_id 필수(필터 없는 경로 차단)."""
        if not role or not user_id:
            raise ValueError("role and user_id are required")
        conds = []
        for grade, cell in self._roles.get(role, {}).items():
            if cell["decision"] in _RETRIEVABLE:
                conds.append(GradeCond(grade, cell.get("scope")))
        return conds


def build_where(
    conds: list[GradeCond],
    *,
    user_id: str,
    grade_col: str = "grade",
    owner_col: str = "owner_id",
    shared_col: str = "shared_with",
) -> tuple[str, dict]:
    """FilterSpec → 파라미터화된 WHERE 절. 문자열 연결 금지, 바인딩만(인젝션 방지).

    공유(scope=shared)는 B2 스키마대로 `resumes.shared_with` JSONB
    `[{"user_id", "expires_at"}]`를 풀어 요청자 원소의 만료 전 여부를 본다.
    허용 등급이 하나도 없으면 'FALSE' (결과 없음)로 안전하게 닫는다.
    """
    clauses: list[str] = []
    params: dict = {}
    for i, c in enumerate(conds):
        gp = f"g{i}"
        params[gp] = c.grade
        if c.scope in (None, "all"):
            clauses.append(f"{grade_col} = :{gp}")
        elif c.scope == "own":
            clauses.append(f"({grade_col} = :{gp} AND {owner_col} = :uid)")
            params["uid"] = user_id
        elif c.scope == "shared":
            clauses.append(
                f"({grade_col} = :{gp} AND EXISTS ("
                f" SELECT 1 FROM jsonb_array_elements({shared_col}) AS e"
                f" WHERE e->>'user_id' = :uid AND (e->>'expires_at')::timestamptz > now()))"
            )
            params["uid"] = user_id
        else:
            raise ValueError(f"unknown scope: {c.scope}")
    if not clauses:
        return ("FALSE", {})
    return (" OR ".join(clauses), params)
