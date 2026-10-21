"""A5 — 출력 검사.

모델 응답을 사용자에게 돌려주기 **직전**에 마지막으로 거르는 지점이다.
입력을 아무리 막아도 응답에 섞여 나올 수 있는 것이 있다.

    1. 원문 PII        토큰화(A1)가 놓친 값, 모델이 지어낸 값
    2. 기밀 청크        검색(C3)이 가져온 다른 사용자·내부 문서 조각
    3. 카나리 토큰      기밀 문서에 심어둔 표식. 나오면 유출 확정
    4. 시스템 프롬프트   지침·템플릿 조각
    5. 키·토큰          로그·환경변수에서 흘러든 자격증명

★ **복원(detokenize)보다 먼저** 부른다. 복원 후에 검사하면 방금 되돌려놓은
  진짜 이름과 전화번호가 전부 PII 로 걸려 모든 응답이 경고가 된다 (A1 제안서 8장).
  그래서 이 함수가 보는 본문에는 아직 ``[[PERSON_1]]`` 같은 토큰이 들어 있다.

판정은 ``allow`` / ``block`` / ``mask`` 세 값이다 (spec 10.1, B1 정리).
그 외의 신호는 ``flags`` 배열로 넘겨 감사 로그(B3)에 남긴다. 네 번째 판정을 만들지 않는다.

부작용이 없다. DB 도 네트워크도 모른다 — 입력과 출력만으로 테스트가 끝난다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.guardrail.schema import (
    CANARY_RULE_ID,
    Decision,
    Finding,
    Severity,
    Verdict,
)
from app.pii import detect, mask

#: 이 모듈이 내리는 판정의 단계 이름 (audit_logs.decision_stage)
STAGE = "output_guard"

#: 유출로 볼 "그대로 일치하는 연속 구간"의 길이 (정규화 후 글자 수).
#:
#: 조각 하나가 일치한다는 것은 곧 이 길이 이상의 연속 구간이 똑같다는 뜻이다.
#: 그래서 이 값이 곧 판정 기준이다.
#:
#: 처음 40자로 잡았다가 테스트에서 내렸다. 기밀 문서의 **한 문장만 베낀** 경우가
#: 정규화 후 39자여서 통째로 빠져나갔다. 25자는 한국어로 한 구절 정도다.
#:
#: ⚠ 낮출수록 자소서 상투구("어려서부터 새로운 것에 도전하는 것을 좋아했습니다" 같은)가
#:   우연히 일치할 위험이 커진다. ``confidential_chunks`` 에 **보이면 안 되는 문서만**
#:   넣는 것이 전제다. 정확한 값은 B21 과차단율 측정으로 조정한다.
SHINGLE_SIZE = 25

#: 두 텍스트 중 짧은 쪽이 조각 길이에 못 미칠 때 통째로 대조하는 최소 길이.
#: 이보다 짧으면 대조하지 않는다 — 우연 일치가 너무 흔해진다.
MIN_SHORT_MATCH = 16

#: A1 이 만든 토큰 모양. 출력에 섞인 토큰을 찾을 때 쓴다.
_TOKEN_RE = re.compile(r"\[\[([A-Z]+)_(\d+)\]\]")

#: 자격증명 모양. 오탐이 거의 없는 것만 넣는다 —
#: 일반적인 긴 문자열까지 잡으면 자소서 본문이 걸린다.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("sk_token", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}=*")),
)


# --------------------------------------------------------------------------
# 결과 구조
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class OutputCheckResult:
    """출력 검사 결과.

    판정 자체는 A4 스키마(``Verdict``)를 쓴다. 여기서 더 들고 있는 것은
    **내보낼 본문** 하나뿐이다 — 다른 단계와 달리 이 단계는 본문을 바꾼다.
    """

    decision: Decision
    #: 내보낼 본문.
    #: - allow: 원본 그대로
    #: - mask: PII 를 가린 본문
    #: - block: **빈 문자열**. 호출자가 실수로 이 값을 내보내도 유출되지 않는다.
    #:   사용자에게 보여줄 안내 문구는 A9 가 만든다
    text: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def verdict(self) -> Verdict:
        """A4 판정 구조체. A8 이 다른 단계의 판정과 합친다."""
        return Verdict(decision=self.decision, stage=STAGE, findings=tuple(self.findings))

    @property
    def flags(self) -> list[str]:
        """감사 로그(B3)의 ``flags`` 배열에 그대로 넣는 값."""
        return self.verdict.flags

    @property
    def rule_id(self) -> str | None:
        """감사 로그의 대표 규칙 하나."""
        return self.verdict.rule_id

    @property
    def canary_hit(self) -> bool:
        return self.verdict.canary_hit

    @property
    def ok(self) -> bool:
        return self.decision == "allow"


@dataclass(frozen=True)
class OutputContext:
    """이 응답에 **들어가면 안 되는 것**들.

    호출자(A8)가 채운다. 비워 두면 그 검사만 건너뛴다 — 모르는 것을 추측하지 않는다.
    """

    #: 시스템 프롬프트·템플릿 본문. 조각이 응답에 섞이면 지침 유출이다
    system_prompt: str | None = None

    #: 기밀 문서에 심어둔 표식. 응답에 나오면 유출 확정이다
    canaries: tuple[str, ...] = ()

    #: 검색(C3)이 가져왔으나 **이 사용자에게 보이면 안 되는** 청크.
    #: ★ 본인 자소서는 넣지 않는다. 넣으면 자기 글을 인용한 정상 응답이 전부 차단된다
    confidential_chunks: tuple[str, ...] = ()

    #: tokenize 가 만든 토큰 전체. 주면 그 밖의 토큰을 "모르는 토큰"으로 표시한다.
    #: 비워 두면 이 검사를 건너뛴다 — 모든 토큰이 모르는 토큰이 되어 버린다
    allowed_tokens: frozenset[str] = frozenset()


EMPTY_CONTEXT = OutputContext()


# --------------------------------------------------------------------------
# 대조용 정규화
# --------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """공백을 전부 지우고 NFKC·casefold 한다.

    줄바꿈을 넣거나 띄어쓰기를 바꿔서 대조를 피하는 것을 막는다. 사람이 읽기에
    같은 글이면 같은 문자열이 되어야 한다.
    """
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", "", text)
    return text.casefold()


def _shingles(text: str, size: int = SHINGLE_SIZE) -> set[str]:
    if len(text) < size:
        return set()
    return {text[i : i + size] for i in range(len(text) - size + 1)}


def _overlaps(output_norm: str, source: str) -> bool:
    """출력과 ``source`` 에 ``SHINGLE_SIZE`` 자 이상 똑같은 연속 구간이 있는가.

    **양쪽 모두** 조각으로 쪼개 교집합을 본다. 한쪽만 쪼개면 그쪽보다 짧은 상대는
    아무것도 걸리지 않는다 — 긴 기밀 문서에서 한 문장만 베껴 온 응답이 그 경우다.
    """
    source_norm = _normalize(source)
    if not source_norm or not output_norm:
        return False

    if min(len(source_norm), len(output_norm)) < SHINGLE_SIZE:
        # 조각을 만들 수 없을 만큼 짧다. 짧은 쪽이 긴 쪽에 통째로 들어 있는지 본다
        if min(len(source_norm), len(output_norm)) < MIN_SHORT_MATCH:
            return False
        return source_norm in output_norm or output_norm in source_norm

    return bool(_shingles(source_norm) & _shingles(output_norm))


# --------------------------------------------------------------------------
# 검사
# --------------------------------------------------------------------------

def check_output(text: str, *, context: OutputContext = EMPTY_CONTEXT) -> OutputCheckResult:
    """모델 응답을 검사하고 판정을 돌려준다.

    ★ ``detokenize`` 보다 **먼저** 부른다.

    한 번에 전부 검사하고 가장 무거운 판정을 돌려준다. 첫 번째 신호에서 멈추지 않는다 —
    감사 로그에는 걸린 것이 전부 남아야 나중에 규칙을 고칠 근거가 된다.
    """
    if not text:
        return OutputCheckResult(decision="allow", text=text)

    findings: list[Finding] = []
    output_norm = _normalize(text)

    # 1. 카나리 — 나왔다는 사실 자체가 유출 확정이다. 가장 먼저 본다
    hits = sum(1 for c in context.canaries if c and _normalize(c) in output_norm)
    if hits:
        findings.append(Finding(CANARY_RULE_ID, "critical", hits))

    # 2. 기밀 청크 — 다른 사용자 문서가 섞여 나왔다
    hits = sum(1 for chunk in context.confidential_chunks if _overlaps(output_norm, chunk))
    if hits:
        findings.append(Finding("LEAK_OTHER_USER", "critical", hits))

    # 3. 시스템 프롬프트 조각
    if context.system_prompt and _overlaps(output_norm, context.system_prompt):
        findings.append(Finding("INJ_SYSPROMPT", "critical", 1))

    # 4. 자격증명
    for rule_name, pattern in _SECRET_PATTERNS:
        found = len(pattern.findall(text))
        if found:
            findings.append(Finding(f"LEAK_SECRET.{rule_name}", "critical", found))

    # 5. 원문 PII — 토큰화가 놓쳤거나 모델이 지어낸 값.
    #    차단이 아니라 마스킹이다. 응답 자체는 쓸모가 있을 수 있다
    pii_counts: dict[str, int] = {}
    for hit in detect(text):
        pii_counts[hit.rule_id] = pii_counts.get(hit.rule_id, 0) + 1
    for rule_id, count in sorted(pii_counts.items()):
        findings.append(Finding(rule_id, "warn", count))

    # 6. 모르는 토큰 — 모델이 토큰을 지어냈다.
    #    복원 단계에서도 unresolved 로 잡히지만, 그때는 이미 사용자에게 갈 본문이다
    if context.allowed_tokens:
        unknown = {
            m.group(0) for m in _TOKEN_RE.finditer(text) if m.group(0) not in context.allowed_tokens
        }
        if unknown:
            findings.append(Finding("OUT_UNKNOWN_TOKEN", "info", len(unknown)))

    return OutputCheckResult(decision=_decide(findings), text=_apply(text, findings), findings=findings)


def _decide(findings: list[Finding]) -> Decision:
    """가장 무거운 신호가 판정을 정한다. critical > warn > info."""
    if any(f.severity == "critical" for f in findings):
        return "block"
    if any(f.severity == "warn" for f in findings):
        return "mask"
    return "allow"


def _apply(text: str, findings: list[Finding]) -> str:
    decision = _decide(findings)
    if decision == "block":
        # 본문을 돌려주지 않는다. 호출자가 실수로 .text 를 내보내도 유출되지 않는다
        return ""
    if decision == "mask":
        return mask(text)
    return text
