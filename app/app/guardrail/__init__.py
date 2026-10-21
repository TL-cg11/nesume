"""가드레일 패키지 — LLM 호출은 전부 여기를 지난다.

★ 기능 코드(B·C 팀 포함)는 이 패키지의 **A8 파이프라인**만 호출한다.
  `llm_client` 를 기능에서 직접 import 하지 않는다. CI가 grep으로 막는다 (D11).

현재 들어 있는 것: A2 LLM 클라이언트 래퍼 · A5 출력 검사.
앞으로 들어올 것: A3 질의 분류 · A8 파이프라인 조립.

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
from app.guardrail.output_guard import (
    EMPTY_CONTEXT,
    SHINGLE_SIZE,
    Decision,
    OutputCheckResult,
    OutputContext,
    OutputFinding,
    Severity,
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
    # A5 출력 검사
    "check_output",
    "OutputCheckResult",
    "OutputContext",
    "OutputFinding",
    "EMPTY_CONTEXT",
    "SHINGLE_SIZE",
    "Decision",
    "Severity",
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
