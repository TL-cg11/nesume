"""테스트용 가짜 제공자.

제공자가 미정이라 실물로 검증할 수 없다. 그래서 **실패 시나리오를 스크립트로 주고**
클라이언트가 그에 어떻게 반응하는지만 본다. 실제 어댑터가 붙으면 이 가짜는 그대로 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.guardrail.llm_client import LlmRequest, LlmResponse, Usage


@dataclass
class FakeProvider:
    """호출을 기록하고, 미리 정해둔 예외를 순서대로 던진다.

    ``failures`` 에 담긴 예외를 앞에서부터 하나씩 던지고, 다 쓰면 정상 응답을 준다.
    """

    model: str = "fake-model-1"
    failures: list[BaseException] = field(default_factory=list)
    reply: str = "응답입니다"
    stop_reason: str = "stop"
    input_tokens: int = 10
    output_tokens: int = 5
    #: 어댑터가 지연을 채우지 않은 상황을 재현하려면 0으로 둔다
    latency_ms: int = 0

    calls: list[LlmRequest] = field(default_factory=list)
    timeouts: list[float] = field(default_factory=list)

    @property
    def model_id(self) -> str:
        return self.model

    async def generate(self, request: LlmRequest, *, timeout_s: float) -> LlmResponse:
        self.calls.append(request)
        self.timeouts.append(timeout_s)

        if self.failures:
            raise self.failures.pop(0)

        return LlmResponse(
            text=self.reply,
            usage=Usage(
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                model=self.model,
            ),
            stop_reason=self.stop_reason,
            latency_ms=self.latency_ms,
        )


@dataclass
class HangingProvider:
    """타임아웃을 지키지 않는 어댑터. 클라이언트가 한 겹 더 막는지 본다."""

    model: str = "hanging-model"

    @property
    def model_id(self) -> str:
        return self.model

    async def generate(self, request: LlmRequest, *, timeout_s: float) -> LlmResponse:
        import asyncio

        await asyncio.sleep(3600)  # timeout_s 를 무시한다
        raise AssertionError("여기까지 오면 안 된다")  # pragma: no cover


class SleepRecorder:
    """실제로 기다리지 않고 대기 시간만 기록한다."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
