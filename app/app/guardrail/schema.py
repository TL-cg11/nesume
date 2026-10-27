"""A4 — 분류 결과 스키마.

A3(질의 분류)·C6(검색 필터)·A5(출력 검사)가 각각 판정을 내리고, A8이 그것을 합쳐
감사 로그(B3) 한 행으로 남긴다. **세 단계가 같은 모양으로 말해야** 합친 결과가
의미를 갖는다. 그 모양을 여기 한 곳에 둔다.

## 판정은 세 값이다

``tasks.md`` A4 에는 처리가 ``allow/block/mask/flag`` 네 값으로 적혀 있다.
그런데 **이미 머지된 코드가 세 값을 쓰고 있다.**

- ``models/audit.py`` — ``DECISIONS = ("allow", "block", "mask")`` 가 DB CHECK 제약
- ``policy/matrix.yaml`` — 모든 칸이 ``allow`` / ``block`` / ``mask``
- ``policy/policy.py`` — ``decision()`` 이 그 셋만 돌려줌

``flag`` 는 판정이 아니라 **표식**이다. ``tasks.md`` A3 의 "권한 외는 flag 만,
하드 차단은 명시 패턴 한정" 도 같은 뜻이다 — 권한 밖 질의는 막지 않고 표시만 남긴다.
그래서 판정은 셋, 표식은 ``flags`` 배열로 둔다. 네 번째 판정을 만들지 않는다.

## 왜 길이를 검사하는가

감사 로그는 B11 이 요청 종료 시 ``finally`` 에서 한 번 쓴다. 거기서 INSERT 가
실패하면 **그 요청의 감사 기록만 통째로 사라진다** — 하필 뭔가 걸렸던 요청이다.
``rule_id`` 는 ``String(50)``, ``flags`` 는 ``ARRAY(String(50))`` 이므로
값을 만드는 쪽에서 미리 막는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# --------------------------------------------------------------------------
# 값 목록 — models/audit.py 의 DB CHECK 제약과 **반드시** 같아야 한다
# --------------------------------------------------------------------------

Decision = Literal["allow", "block", "mask"]
DECISIONS: tuple[Decision, ...] = ("allow", "block", "mask")

#: 질의 유형 (A3 산출). audit_logs.query_type 의 허용값.
QueryType = Literal["normal", "out_of_scope", "sensitive", "exfiltration"]
QUERY_TYPES: tuple[QueryType, ...] = ("normal", "out_of_scope", "sensitive", "exfiltration")

#: 판정을 내린 단계. audit_logs.decision_stage 의 허용값.
DecisionStage = Literal["classifier", "retriever", "output_guard"]
DECISION_STAGES: tuple[DecisionStage, ...] = ("classifier", "retriever", "output_guard")

Severity = Literal["info", "warn", "critical"]
SEVERITIES: tuple[Severity, ...] = ("info", "warn", "critical")

#: 카나리 적중 규칙. audit_logs.canary_hit 불리언 컬럼으로도 따로 나간다 —
#: 카나리는 탐지율 100% 가 목표(5단계)라 집계를 flags 배열 안에서 세지 않는다.
CANARY_RULE_ID = "LEAK_CANARY"

#: audit_logs 컬럼 길이 (models/audit.py)
MAX_RULE_ID_LEN = 50
MAX_FLAG_LEN = 50

#: 무거운 순서. 합칠 때 더 무거운 쪽이 이긴다.
_DECISION_RANK: dict[str, int] = {"allow": 0, "mask": 1, "block": 2}
_SEVERITY_RANK: dict[str, int] = {"info": 0, "warn": 1, "critical": 2}


def worse_decision(a: Decision, b: Decision) -> Decision:
    return a if _DECISION_RANK[a] >= _DECISION_RANK[b] else b


def decision_rank(decision: Decision) -> int:
    return _DECISION_RANK[decision]


def severity_rank(severity: Severity) -> int:
    return _SEVERITY_RANK[severity]


# --------------------------------------------------------------------------
# 걸린 것 하나
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    """규칙 하나가 걸린 사실.

    ★ 값을 담지 않는다. 종류·심각도·개수만 담는다. 걸린 내용을 담으면 감사 로그와
      화면에 그 값이 그대로 남는다 — A1 의 ``Hit`` 과 같은 판단이다.

    ``severity`` 에서 판정을 자동으로 끌어내지 않는다. 같은 ``warn`` 이라도
    입력 단계에서는 표시만 하고 출력 단계에서는 가리는 식으로 다르다.
    판정은 각 단계가 정하고, 이 구조체는 사실만 나른다.
    """

    rule_id: str
    severity: Severity
    count: int = 1

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("rule_id 가 비어 있습니다")
        if len(self.rule_id) > MAX_RULE_ID_LEN:
            raise ValueError(
                f"rule_id 가 {MAX_RULE_ID_LEN}자를 넘습니다 — "
                f"audit_logs 에 들어가지 못합니다: {self.rule_id!r}"
            )
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity 는 {SEVERITIES} 중 하나여야 합니다: {self.severity!r}")
        if self.count < 1:
            raise ValueError("count 는 1 이상이어야 합니다")


# --------------------------------------------------------------------------
# 한 단계의 판정
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Verdict:
    """한 단계가 내린 판정. A8 이 단계별 판정을 합쳐 감사 로그 한 행을 만든다."""

    decision: Decision
    stage: DecisionStage
    findings: tuple[Finding, ...] = ()
    #: 분류 단계에서만 채운다. 다른 단계는 None
    query_type: QueryType | None = None

    def __post_init__(self) -> None:
        if self.decision not in DECISIONS:
            raise ValueError(f"decision 은 {DECISIONS} 중 하나여야 합니다: {self.decision!r}")
        if self.stage not in DECISION_STAGES:
            raise ValueError(f"stage 는 {DECISION_STAGES} 중 하나여야 합니다: {self.stage!r}")
        if self.query_type is not None and self.query_type not in QUERY_TYPES:
            raise ValueError(f"query_type 은 {QUERY_TYPES} 중 하나여야 합니다: {self.query_type!r}")

    # ------------------------------------------------------------ 파생 값

    @property
    def flags(self) -> list[str]:
        """``audit_logs.flags`` 배열. 순서는 걸린 순서를 유지하고 중복만 없앤다."""
        return list(dict.fromkeys(f.rule_id for f in self.findings))

    @property
    def rule_id(self) -> str | None:
        """``audit_logs.rule_id`` 에 넣을 **대표 규칙 하나**.

        로그 컬럼이 하나뿐이라 여럿 걸렸을 때 무엇을 남길지 정해야 한다.
        **가장 무거운 것, 동률이면 먼저 걸린 것**을 쓴다. 나머지는 ``flags`` 에 남으므로
        잃는 정보는 없고, 대시보드(D15)에서 "무엇 때문에 막혔나"를 바로 볼 수 있다.
        """
        if not self.findings:
            return None
        return max(self.findings, key=lambda f: _SEVERITY_RANK[f.severity]).rule_id

    @property
    def canary_hit(self) -> bool:
        """``audit_logs.canary_hit``. 배열을 뒤지지 않아도 되게 따로 뽑는다."""
        return any(f.rule_id == CANARY_RULE_ID for f in self.findings)

    @property
    def ok(self) -> bool:
        return self.decision == "allow"

    # ------------------------------------------------------------ 합치기

    def merge(self, other: Verdict) -> Verdict:
        """두 단계의 판정을 합친다.

        - 판정: 더 무거운 쪽 (block > mask > allow)
        - 단계: **무거운 판정을 만든 단계.** 어디서 막혔는지가 로그의 쓸모다
        - 표식: 양쪽을 순서대로 합치고 중복 제거
        - 질의 유형: **무거운 판정을 만든 쪽의 값.** 그 쪽이 비었으면 다른 쪽 값을 쓴다

        ★ 질의 유형이 단계를 따라가는 이유 — **막은 쪽이 왜 막았는지를 말해야 한다.**
          전에는 "먼저 정해진 값을 유지" 였다. 그런데 A12 가 이력을 보고 탈취로
          판정해도 A3 가 이 턴만 보고 내린 ``normal`` 이 먼저 정해진 값이라 이겼고,
          **감사 로그가 막은 이유를 틀리게 적었다** (A10-MULTI-04 측정에서 드러났다).

          무거운 쪽이 비어 있을 때만 가벼운 쪽 값을 쓴다. 그래서 유형을 정하지 않는
          단계(출력 검사)가 막을 때는 분류 단계가 정한 값이 그대로 남는다.
        """
        decision = worse_decision(self.decision, other.decision)
        # 동률이면 먼저 내려진 판정을 남긴다 — 파이프라인 앞쪽이 원인이다
        if _DECISION_RANK[other.decision] > _DECISION_RANK[self.decision]:
            stage, heavier, lighter = other.stage, other.query_type, self.query_type
        else:
            stage, heavier, lighter = self.stage, self.query_type, other.query_type
        query_type = heavier if heavier is not None else lighter

        seen: dict[str, Finding] = {}
        for finding in (*self.findings, *other.findings):
            existing = seen.get(finding.rule_id)
            if existing is None:
                seen[finding.rule_id] = finding
            else:
                # 같은 규칙이 두 단계에서 걸리면 개수를 더하고 무거운 심각도를 남긴다
                severity = max(
                    (existing.severity, finding.severity), key=lambda s: _SEVERITY_RANK[s]
                )
                seen[finding.rule_id] = Finding(
                    rule_id=finding.rule_id,
                    severity=severity,  # type: ignore[arg-type]
                    count=existing.count + finding.count,
                )

        return Verdict(
            decision=decision,
            stage=stage,  # type: ignore[arg-type]
            findings=tuple(seen.values()),
            query_type=query_type,
        )

    # ------------------------------------------------------------ 감사 로그

    def to_audit_fields(self) -> dict[str, object]:
        """``audit_logs`` 에 넣을 필드. B11 이 ``**`` 로 펼쳐 쓴다.

        나머지 컬럼(request_id·user_id·latency_ms 등)은 A8 이 채운다 —
        판정에서 알 수 없는 값이다.
        """
        flags = self.flags
        too_long = [f for f in flags if len(f) > MAX_FLAG_LEN]
        if too_long:  # pragma: no cover - Finding 생성 시 이미 막힌다
            raise ValueError(f"flags 항목이 {MAX_FLAG_LEN}자를 넘습니다: {too_long}")

        return {
            "decision": self.decision,
            "decision_stage": self.stage,
            "query_type": self.query_type,
            "flags": flags,
            "rule_id": self.rule_id,
            "canary_hit": self.canary_hit,
        }


def allow(stage: DecisionStage, *, query_type: QueryType | None = None) -> Verdict:
    """아무것도 걸리지 않은 판정. 단계마다 쓰는 기본값이다."""
    return Verdict(decision="allow", stage=stage, query_type=query_type)


EMPTY_FINDINGS: tuple[Finding, ...] = ()
