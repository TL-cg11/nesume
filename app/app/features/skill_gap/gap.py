"""C10 — 역량 갭 계산 (순수 로직, DB·A11 무관).

C가 역량 데이터 모양(`RequiredCompetency`)을 정의하고, A11 출력은 어댑터가 이 모양으로 매핑한다.
갭 = 요구 역량 − 보유 역량(정규화 키 매칭), 중요도(필수/우대 × 빈도)순 정렬.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

#: 중요도 가중치 — 필수 > 우대. 운영에서 조정하려면 이 값만 바꾼다.
ESSENTIAL_WEIGHT = 2.0
PREFERRED_WEIGHT = 1.0


@dataclass(frozen=True)
class RequiredCompetency:
    """공고가 요구하는 역량 1건(A11 추출 → 어댑터가 이 모양으로 공급)."""

    key: str                    # 정규화 식별자(이름/NCS 코드) — 매칭 기준
    label: str                  # 표시용 원문 이름
    essential: bool             # 필수(True) / 우대(False)
    frequency: int = 1          # 공고 내 등장 빈도
    evidence: str | None = None  # 근거(원문 위치·문장)


@dataclass(frozen=True)
class GapItem:
    """사용자가 아직 안 가진 요구 역량(중요도 포함)."""

    key: str
    label: str
    importance: float
    essential: bool
    evidence: str | None


def importance(competency: RequiredCompetency) -> float:
    """표시용 중요도 점수 = (필수 2.0 / 우대 1.0) × 빈도. 빈도 최소 1."""
    weight = ESSENTIAL_WEIGHT if competency.essential else PREFERRED_WEIGHT
    return weight * max(competency.frequency, 1)


def compute_gap(
    required: Iterable[RequiredCompetency],
    held_keys: Iterable[str],
) -> list[GapItem]:
    """요구 역량 중 보유하지 않은 것(갭)을 정렬해 반환.

    `held_keys`는 사용자 보유 역량의 정규화 키 집합(경험·스킬에서 추출). 같은 키면 보유로 본다.
    정렬: **필수 역량 먼저**(must-have 우선, 빈도 무관) → 같은 등급 내 **빈도 높은 순**.
    `importance`는 화면 표시용 점수(정렬 1차 기준 아님).
    """
    held = set(held_keys)
    gaps = [c for c in required if c.key not in held]
    gaps.sort(key=lambda c: (c.essential, c.frequency), reverse=True)
    return [
        GapItem(c.key, c.label, importance(c), c.essential, c.evidence)
        for c in gaps
    ]
