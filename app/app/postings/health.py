"""C4 — 수집 건강성 게이트 (순수 로직, docs/C4.md 결정3 보정).

수집량이 비정상이면(장애 의심) 사라짐 처리를 동결하기 위한 판정. DB·외부 의존 없음
(upsert.py가 이 판정을 받아 DB 전이를 집행). 기준선은 "달력상 어제"가 아니라
**최근 정상 수집의 중앙값** — 공휴일·주말·결번에 면역.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

#: 비활성 공고가 이 횟수(정상 수집)만큼 안 보이면 물리 삭제 후보(참조 없을 때만). docs/C4.md 결정2.
DELETE_CANDIDATE_STREAK = 30
#: 가드가 오래 걸려도 이 횟수 넘게 안 보이면 무조건 비활성(동결 상한). docs/C4.md 결정3 백스톱.
BACKSTOP_STREAK = 90


@dataclass(frozen=True)
class GateDecision:
    healthy: bool          # 이번 수집을 신뢰할 수 있는가(upsert는 어느 경우든 적용)
    process_absences: bool # 사라짐 처리(비활성·streak++)를 돌려도 되는가
    reason: str
    baseline: float | None


def evaluate_health(
    today_count: int,
    recent_counts: list[int],
    *,
    rel: float = 0.80,
    floor: float = 0.50,
    bootstrap_runs: int = 7,
) -> GateDecision:
    """오늘 수집량이 정상인지 판정(소스별).

    - 이력 < bootstrap_runs → 부트스트랩: 수집·upsert는 하되 **사라짐 처리는 보류**.
    - 기준선 = 최근 정상 수집 건수의 **중앙값**(공휴일·결번 면역).
    - today < 기준선×floor → 절대 하한 위반(서서히 끓기 차단) → 비정상.
    - today < 기준선×rel  → 상대 급감 → 비정상.
    - 그 외 정상.
    """
    if len(recent_counts) < bootstrap_runs:
        return GateDecision(True, False, "bootstrap", None)
    baseline = float(median(recent_counts))
    if baseline <= 0:
        return GateDecision(True, False, "no-baseline", baseline)
    ratio = today_count / baseline
    if ratio < floor:
        return GateDecision(False, False, f"below-floor({ratio:.2f})", baseline)
    if ratio < rel:
        return GateDecision(False, False, f"below-rel({ratio:.2f})", baseline)
    return GateDecision(True, True, f"ok({ratio:.2f})", baseline)
