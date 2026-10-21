"""A3 — 질의 유형 분류기.

사용자 질의를 네 유형으로 나눈다 — ``normal`` / ``out_of_scope`` / ``sensitive`` /
``exfiltration``. 값 목록은 ``audit_logs.query_type`` 의 DB CHECK 제약과 같다.

규칙은 코드가 아니라 ``classifier_rules.yaml`` 에 둔다. 배포 없이 고칠 수 있어야 하고,
변경 이력이 그 파일 하나로 남아야 하기 때문이다. 대신 로더가 엄격하게 검사한다 —
오타 하나로 규칙이 조용히 빠지면 탐지가 사라진 줄도 모른다.

## 권한 밖은 막지 않는다

``tasks.md`` A3 의 **"권한 외는 flag 만, 하드 차단은 명시 패턴 한정"** 을 그대로 따른다.

``matrix.yaml`` 이 역할×등급을 ``block`` 이라고 해도, **분류 단계에서는 막지 않고
표시만 남긴다.** 그 ``block`` 은 "그 문서를 검색 결과에 넣지 않는다"는 뜻이고,
실제 제외는 C6 검색 필터가 한다. 분류 단계에서 질의 자체를 막으면 사용자는
"내 자소서 얘기를 했는데 왜 막히지?" 같은 과차단을 겪는다.

하드 차단(``block``)은 ``exfiltration`` 로 분류된 **명시 패턴**에만 적용한다.

## 다른 겹과의 관계

C5 는 **외부 텍스트**(공고·README)에 섞여 들어온 지시를 중화한다. A3 는 **사용자가
직접 친 질의**를 본다. 같은 문구를 양쪽에서 보지만 겹치는 것이 맞다 — 다층 방어다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import yaml

from app.guardrail.schema import (
    QUERY_TYPES,
    SEVERITIES,
    Decision,
    Finding,
    QueryType,
    Severity,
    Verdict,
)

#: 이 모듈이 내리는 판정의 단계 이름 (audit_logs.decision_stage)
STAGE = "classifier"

#: 규칙 파일. A 소유 경로에 둔다
RULES_PATH = Path(__file__).with_name("classifier_rules.yaml")

#: 질의 유형 → 판정.
#:
#: ★ out_of_scope 가 allow 인 것이 이 표의 핵심이다 (tasks.md A3 "권한 외는 flag 만").
#:   표시는 flags 로 남고, 실제 문서 제외는 C6 검색 필터가 한다.
#:
#: sensitive 를 mask 로 두는 이유: matrix.yaml 이 sensitive 등급을 mask 로 다룬다.
#: 분류 단계에서 가릴 것은 없지만, 이 판정이 A5 까지 흘러가 출력에서 가려진다.
TYPE_TO_DECISION: dict[QueryType, Decision] = {
    "normal": "allow",
    "out_of_scope": "allow",
    "sensitive": "mask",
    "exfiltration": "block",
}


class PolicyLike(Protocol):
    """C2 정책 로더(``app.policy.policy.Policy``)에서 쓰는 부분만.

    프로토콜로 받는 이유: C 소유 모듈을 직접 import 하면 A 테스트가 그 파일과
    ``matrix.yaml`` 에 묶인다. 필요한 모양만 적고 주입받는다.
    """

    def decision(self, role: str, grade: str) -> tuple[str, str | None]: ...


class RuleFileError(Exception):
    """규칙 파일이 잘못됐다. 기동 단계에서 터뜨린다 — 조용히 넘기면 탐지가 사라진다."""


@dataclass(frozen=True)
class Rule:
    rule_id: str
    query_type: QueryType
    severity: Severity
    priority: int
    patterns: tuple[re.Pattern[str], ...]
    #: 이 역할에게는 적용하지 않는다
    exempt_roles: frozenset[str] = frozenset()
    #: 이 질의가 요구하는 문서 등급. 있으면 matrix.yaml 로 역할×등급을 본다
    grade: str | None = None
    #: 남의 것을 달라는 질의인가. matrix 가 allow 라도 scope 가 own/shared 면
    #: "본인 것만 볼 수 있다"는 뜻이므로 권한 밖으로 본다
    other_owner: bool = False

    def applies_to(self, role: str) -> bool:
        return role not in self.exempt_roles

    def matches(self, text: str) -> bool:
        return any(p.search(text) for p in self.patterns)


# --------------------------------------------------------------------------
# 규칙 로딩
# --------------------------------------------------------------------------

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuleFileError(message)


def load_rules(path: Path | str = RULES_PATH) -> tuple[Rule, ...]:
    """규칙 파일을 읽어 검사한다.

    오타·빠진 값은 전부 여기서 막는다. 규칙 하나가 조용히 빠지면 그 탐지가
    사라진 줄도 모른 채로 돈다.
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    _require(isinstance(data, dict), "규칙 파일 최상위는 맵이어야 합니다")
    _require("rules" in data, "'rules' 키가 없습니다")

    rules: list[Rule] = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(data["rules"]):
        where = f"rules[{index}]"
        _require(isinstance(raw, dict), f"{where} 는 맵이어야 합니다")

        rule_id = raw.get("rule_id")
        _require(bool(rule_id), f"{where}.rule_id 가 없습니다")
        _require(rule_id not in seen_ids, f"rule_id 가 중복됩니다: {rule_id}")
        seen_ids.add(rule_id)

        query_type = raw.get("query_type")
        _require(
            query_type in QUERY_TYPES,
            f"{rule_id}.query_type 은 {QUERY_TYPES} 중 하나여야 합니다: {query_type!r}",
        )

        severity = raw.get("severity", "warn")
        _require(
            severity in SEVERITIES,
            f"{rule_id}.severity 는 {SEVERITIES} 중 하나여야 합니다: {severity!r}",
        )

        priority = raw.get("priority")
        _require(isinstance(priority, int), f"{rule_id}.priority 는 정수여야 합니다")

        raw_patterns = raw.get("patterns") or []
        _require(bool(raw_patterns), f"{rule_id}.patterns 가 비어 있습니다")

        compiled: list[re.Pattern[str]] = []
        for pattern in raw_patterns:
            try:
                compiled.append(re.compile(pattern, re.IGNORECASE | re.MULTILINE))
            except re.error as exc:
                raise RuleFileError(f"{rule_id} 의 정규식이 잘못됐습니다: {pattern!r} — {exc}") from exc

        rules.append(
            Rule(
                rule_id=rule_id,
                query_type=query_type,
                severity=severity,
                priority=priority,
                patterns=tuple(compiled),
                exempt_roles=frozenset(raw.get("exempt_roles") or ()),
                grade=raw.get("grade"),
                other_owner=bool(raw.get("other_owner", False)),
            )
        )

    _require(bool(rules), "규칙이 하나도 없습니다")
    # 우선순위 높은 것부터. 같은 우선순위는 파일에 적힌 순서를 유지한다
    return tuple(sorted(rules, key=lambda r: -r.priority))


@lru_cache(maxsize=4)
def _cached_rules(path: str) -> tuple[Rule, ...]:
    return load_rules(path)


# --------------------------------------------------------------------------
# 분류
# --------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """NFKC 정규화 + 제로폭 문자 제거.

    제로폭 문자를 글자 사이에 끼워 정규식을 피하는 것을 막는다. 띄어쓰기는
    규칙 쪽에서 ``\\s*`` 로 받으므로 여기서 지우지 않는다 — 지우면 단어 경계가 사라진다.
    """
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


@dataclass(frozen=True)
class Classification:
    """분류 결과. 판정은 ``verdict`` 로 꺼낸다."""

    query_type: QueryType
    findings: tuple[Finding, ...] = ()
    #: 역할×등급 판정에서 block 이 나온 규칙들. 과차단 분석용
    grade_blocked: tuple[str, ...] = ()

    @property
    def verdict(self) -> Verdict:
        return Verdict(
            decision=TYPE_TO_DECISION[self.query_type],
            stage=STAGE,
            findings=self.findings,
            query_type=self.query_type,
        )


def classify(
    text: str,
    *,
    role: str,
    policy: PolicyLike | None = None,
    rules: tuple[Rule, ...] | None = None,
) -> Classification:
    """질의를 분류한다.

    부작용이 없다. DB 도 네트워크도 모른다 — 규칙 파일만 읽는다.

    ``policy`` 를 주면 ``grade`` 가 적힌 규칙에 대해 역할×등급 판정을 한다.
    주지 않으면 그 검사만 건너뛴다 — 모르는 것을 추측하지 않는다.

    겹치는 규칙은 **우선순위가 높은 것**이 유형을 정한다. 걸린 것은 전부 findings
    에 남는다 — 감사 로그에 다 남아야 나중에 규칙을 고칠 근거가 된다.
    """
    active = rules if rules is not None else _cached_rules(str(RULES_PATH))
    if not text or not text.strip():
        return Classification(query_type="normal")

    normalized = _normalize(text)

    findings: list[Finding] = []
    grade_blocked: list[str] = []
    query_type: QueryType = "normal"
    decided = False

    for rule in active:  # 이미 우선순위 내림차순
        if not rule.applies_to(role) or not rule.matches(normalized):
            continue

        # 등급이 적힌 규칙은 matrix.yaml 로 한 번 더 거른다.
        # 그 역할이 원래 볼 수 있는 등급이면 권한 밖이 아니다
        if rule.grade is not None and policy is not None:
            policy_decision, scope = policy.decision(role, rule.grade)
            if policy_decision == "block":
                grade_blocked.append(rule.rule_id)
            elif rule.other_owner and scope in ("own", "shared"):
                # 볼 수는 있지만 "본인 것만" 이다. 남의 것을 달라는 질의이므로 권한 밖
                grade_blocked.append(rule.rule_id)
            else:
                continue

        findings.append(Finding(rule_id=rule.rule_id, severity=rule.severity))
        if not decided:
            query_type = rule.query_type
            decided = True

    return Classification(
        query_type=query_type,
        findings=tuple(findings),
        grade_blocked=tuple(grade_blocked),
    )
