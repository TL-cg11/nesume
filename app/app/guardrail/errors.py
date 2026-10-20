"""LLM 호출에서 나는 예외.

**재시도해도 되는 것과 안 되는 것을 타입으로 가른다.** 메시지 문자열을 보고
판단하면 제공자를 바꿀 때마다 그 판단이 깨진다.
"""

from __future__ import annotations


class LlmError(Exception):
    """이 패키지에서 나는 모든 오류의 뿌리."""


# ---------------------------------------------------------------- 재시도 가능

class LlmRetryable(LlmError):
    """같은 요청을 다시 보내면 성공할 수 있는 오류."""


class LlmTimeout(LlmRetryable):
    """제공자가 제때 답하지 않았다."""


class LlmThrottled(LlmRetryable):
    """요청량 제한에 걸렸다.

    제공자가 대기 시간을 알려주면 그 값을 쓴다. 우리 쪽 백오프 계산보다 정확하다.
    """

    def __init__(self, message: str = "요청량 제한", retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class LlmTransient(LlmRetryable):
    """제공자 쪽 일시 장애(5xx 등)."""


# ---------------------------------------------------------------- 재시도 불가

class LlmInvalidRequest(LlmError):
    """요청 자체가 잘못됐다. 다시 보내도 같은 결과다 — 재시도하지 않는다."""


class LlmUnavailable(LlmError):
    """제공자가 설정되지 않았다.

    2026-10-20 현재 LLM 제공자·모델이 미정이라 기본 제공자가 이 예외를 던진다.
    정해지면 어댑터를 붙인다 (guardrail/llm_client.py 참조).
    """


class LlmBudgetExceeded(LlmError):
    """한 요청이 쓰기로 한 호출 수나 토큰 수를 넘겼다.

    재시도 대상이 아니다. 호출자가 입력을 줄이거나 상한을 조정해야 한다.
    """
