"""가드레일 패키지 — LLM 호출은 전부 여기를 지난다.

★ 기능 코드(B·C 팀 포함)는 이 패키지의 **A8 파이프라인**만 호출한다.
  `llm_client` 를 기능에서 직접 import 하지 않는다. CI가 grep으로 막는다 (D11).

현재 들어 있는 것: A2 래퍼 · A3 분류 · A4 스키마 · A5 출력 검사 · **A8 파이프라인**.

## A8 — LLM 을 쓰는 모든 기능이 지나는 단 하나의 경로

    guard = Guardrail(llm=..., vault=..., policy=..., retriever=..., audit=...)
    result = await guard.run(query, RequestContext(user_id=..., role=..., feature=...))
    result.text      # 사용자에게 보여줄 본문 (차단이면 빈 문자열)
    result.verdict   # A4 Verdict — 단계별 판정을 합친 것
    result.usage     # 토큰 사용량 (C7 쿼터)

감사 로그(B11)는 `finally` 에서 **정확히 한 번** 쓴다.
C6 검색과 B11 기록은 아직 없어 프로토콜로 두고 주입받는다.

## A3 사용법

    from app.guardrail import classify

    c = classify(user_query, role=token_role, policy=policy)   # policy 는 C2 로더
    c.query_type   # normal | out_of_scope | sensitive | exfiltration
    c.verdict      # A4 Verdict (stage="classifier")

★ 권한 밖(`out_of_scope`)은 **막지 않고 표시만** 한다. 실제 문서 제외는
  C6 검색 필터가 matrix.yaml 로 한다. 하드 차단은 `exfiltration` 명시 패턴에 한정.

## A4 — 단계별 판정의 공통 모양

A3(분류) · C6(검색 필터) · A5(출력 검사)가 각각 `Verdict` 를 만들고,
A8 이 `merge` 로 합쳐 감사 로그(B3) 한 행을 만든다.

    v = classifier_verdict.merge(retriever_verdict).merge(output_verdict)
    await write_audit_log(request_id=..., **v.to_audit_fields())

판정은 `allow` / `block` / `mask` 세 값뿐이다. `flag` 는 판정이 아니라 표식이며
`flags` 배열로 나간다 — 이미 머지된 `models/audit.py` 의 DB 제약과 같다.

## A2 사용법

    from app.guardrail import LlmClient, LlmRequest

    client = LlmClient(provider=provider)       # provider 는 주입
    response = await client.generate(LlmRequest(prompt=...))
    response.text          # 모델 응답
    response.usage         # 토큰 사용량 → C7 쿼터 · B11 감사 로그
    response.truncated     # 출력 상한에 걸려 잘렸는지

분할 호출은 사용량이 합산되어 돌아온다.

    responses, usage = await client.generate_split([req1, req2])

## A5 사용법

    from app.guardrail import check_output, OutputContext

    result = check_output(response.text, context=OutputContext(
        system_prompt=..., canaries=..., confidential_chunks=..., allowed_tokens=...,
    ))
    result.decision    # "allow" | "block" | "mask"
    result.text        # 내보낼 본문 (block 이면 빈 문자열)
    result.flags       # 감사 로그(B3)의 flags 배열

★ **복원(A1 detokenize)보다 먼저** 부른다. 복원 후에 검사하면 방금 되돌려놓은
  진짜 이름과 전화번호가 전부 PII 로 걸려 모든 응답이 경고가 된다.

## 제공자 미정 (2026-10-20)

LLM 제공자·모델이 아직 정해지지 않았다. 기본 제공자는 호출 시
`LlmUnavailable` 을 던진다 — import 와 테스트는 되고 실제 호출만 막힌다.
정해지면 `LlmProvider` 구현 어댑터 한 파일을 추가하고 주입 지점만 바꾼다.
"""

from app.guardrail.errors import (
    LlmBudgetExceeded,
    LlmError,
    LlmInvalidRequest,
    LlmRetryable,
    LlmThrottled,
    LlmTimeout,
    LlmTransient,
    LlmUnavailable,
)
from app.guardrail.schema import (
    CANARY_RULE_ID,
    DECISION_STAGES,
    DECISIONS,
    MAX_FLAG_LEN,
    MAX_RULE_ID_LEN,
    QUERY_TYPES,
    SEVERITIES,
    Decision,
    DecisionStage,
    Finding,
    QueryType,
    Severity,
    Verdict,
    allow,
    decision_rank,
    severity_rank,
    worse_decision,
)
from app.guardrail.pipeline import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TOP_K,
    AuditSink,
    AuditWriteFailed,
    Chunk,
    Guardrail,
    PipelineResult,
    PromptBuilder,
    RequestContext,
    Retriever,
    build_prompt,
)
from app.guardrail.classifier import (
    RULES_PATH,
    TYPE_TO_DECISION,
    Classification,
    PolicyLike,
    Rule,
    RuleFileError,
    classify,
    load_rules,
)
from app.guardrail.output_guard import (
    EMPTY_CONTEXT,
    SHINGLE_SIZE,
    STAGE,
    OutputCheckResult,
    OutputContext,
    check_output,
)
from app.guardrail.llm_client import (
    DEFAULT_MAX_CALLS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_TIMEOUT_S,
    ZERO_USAGE,
    LlmClient,
    LlmProvider,
    LlmRequest,
    LlmResponse,
    NotConfiguredProvider,
    RetryPolicy,
    Usage,
    validate_request,
)

__all__ = [
    # A8 파이프라인
    "Guardrail",
    "RequestContext",
    "PipelineResult",
    "Chunk",
    "Retriever",
    "AuditSink",
    "AuditWriteFailed",
    "PromptBuilder",
    "build_prompt",
    "DEFAULT_SYSTEM_PROMPT",
    "DEFAULT_TOP_K",
    # A3 질의 유형 분류
    "classify",
    "Classification",
    "Rule",
    "RuleFileError",
    "PolicyLike",
    "load_rules",
    "RULES_PATH",
    "TYPE_TO_DECISION",
    # A4 분류 결과 스키마
    "Verdict",
    "Finding",
    "allow",
    "Decision",
    "QueryType",
    "DecisionStage",
    "Severity",
    "DECISIONS",
    "QUERY_TYPES",
    "DECISION_STAGES",
    "SEVERITIES",
    "CANARY_RULE_ID",
    "MAX_RULE_ID_LEN",
    "MAX_FLAG_LEN",
    "worse_decision",
    "decision_rank",
    "severity_rank",
    # A5 출력 검사
    "check_output",
    "OutputCheckResult",
    "OutputContext",
    "EMPTY_CONTEXT",
    "SHINGLE_SIZE",
    "STAGE",
    # 클라이언트
    "LlmClient",
    "RetryPolicy",
    "validate_request",
    # 요청·응답·사용량
    "LlmRequest",
    "LlmResponse",
    "Usage",
    "ZERO_USAGE",
    # 제공자
    "LlmProvider",
    "NotConfiguredProvider",
    # 기본값
    "DEFAULT_MAX_CALLS",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_MAX_OUTPUT_TOKENS",
    # 예외
    "LlmError",
    "LlmRetryable",
    "LlmTimeout",
    "LlmThrottled",
    "LlmTransient",
    "LlmInvalidRequest",
    "LlmUnavailable",
    "LlmBudgetExceeded",
]
