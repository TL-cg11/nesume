"""A2 — LLM 클라이언트 래퍼.

모델 호출을 **한 곳으로 모으는 것**이 목적이다. 기능마다 SDK를 직접 부르면
타임아웃·재시도·토큰 계측이 기능마다 달라지고, 어디서 얼마나 썼는지 알 수 없다.

★ 이 모듈은 가드레일 패키지 안에만 둔다. 기능 코드는 A8 파이프라인만 호출한다
  (tasks.md 공통 규칙 2번, CI에서 grep으로 막는다 — D11).

## 제공자 미정 상태

2026-10-20 현재 LLM 제공자·모델이 정해지지 않았다. 그래서 **제공자를 포트로 분리**하고
기본값은 호출 즉시 `LlmUnavailable` 을 던지는 구현을 둔다. A1에서 치환표 저장을
`VaultStore` 프로토콜로 분리한 것과 같은 방식이다.

정해지면 `LlmProvider` 를 구현한 어댑터 한 파일을 추가하고 주입 지점만 바꾼다.
이 파일과 호출부(A6·A7·A8)는 고치지 않는다.

## 이 모듈이 하지 않는 일

- 프롬프트 조립 (A8)
- PII 토큰화 (A1) · 출력 검사 (A5) · 질의 분류 (A3)
- 감사 로그 쓰기 — 호출자가 `Usage` 를 받아 B11에 한 번만 남긴다
- 쿼터 판정 — `Usage` 를 넘겨주기만 하고 한도 판단은 C7이 한다
- 스트리밍 — 미지원. 토큰이 청크 경계에서 쪼개지면 복원(A1)이 깨진다
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

from app.guardrail.errors import (
    LlmBudgetExceeded,
    LlmInvalidRequest,
    LlmRetryable,
    LlmThrottled,
    LlmTimeout,
    LlmUnavailable,
)

#: 한 번의 사용자 요청이 LLM을 부를 수 있는 최대 횟수.
#: 5,000자 초과 자소서를 나눠 보내는 경우(A6)를 고려한 값이다. 이 상한이 없으면
#: 입력 길이에 따라 호출 수가 무한히 늘어난다.
DEFAULT_MAX_CALLS = 4

#: 한 번의 호출에 기다리는 시간. 자소서 리라이팅은 수 초가 정상이라 짧게 잡지 않는다.
DEFAULT_TIMEOUT_S = 30.0

#: 출력 토큰 상한의 기본값. 제공자별 상한과 무관하게 우리 쪽에서 먼저 막는다.
DEFAULT_MAX_OUTPUT_TOKENS = 2048


# --------------------------------------------------------------------------
# 토큰 사용량 — C7 쿼터가 읽는 값
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Usage:
    """토큰 사용량.

    분할 호출(A6)에서는 여러 번의 호출을 합산해야 하므로 ``+`` 를 정의한다.
    호출자는 합산된 값 하나만 C7과 B11에 넘기면 된다.

    ``model`` 을 담는 이유: 모델이 바뀌면 같은 토큰 수의 비용이 달라진다.
    쿼터를 토큰 수로만 세면 모델 교체 후 집계가 어긋난다.
    """

    input_tokens: int
    output_tokens: int
    model: str
    calls: int = 1

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: Usage) -> Usage:
        if not isinstance(other, Usage):  # pragma: no cover - 방어용
            return NotImplemented
        # 모델이 섞이면 합산값의 의미가 깨진다. 섞인 사실을 숨기지 않고 표시한다.
        model = self.model if self.model == other.model else f"{self.model}+{other.model}"
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            model=model,
            calls=self.calls + other.calls,
        )


ZERO_USAGE = Usage(input_tokens=0, output_tokens=0, model="", calls=0)


# --------------------------------------------------------------------------
# 요청 · 응답
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class LlmRequest:
    """한 번의 모델 호출 입력.

    ★ ``__repr__`` 이 프롬프트 본문을 감춘다. 프롬프트에는 토큰화된 자소서가 들어가고,
      토큰화가 놓친 PII가 섞여 있을 수 있다. 스택트레이스·로그로 새는 경로를
      구조적으로 막는다. A1의 ``Vault`` 와 같은 처리다.
    """

    prompt: str
    system: str | None = None
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    temperature: float = 0.3
    stop: tuple[str, ...] = ()

    def __repr__(self) -> str:
        sys_len = len(self.system) if self.system else 0
        return (
            f"LlmRequest(prompt={len(self.prompt)}자, system={sys_len}자, "
            f"max_output_tokens={self.max_output_tokens}, temperature={self.temperature})"
        )


@dataclass(frozen=True)
class LlmResponse:
    """모델 응답.

    ``truncated`` 를 따로 두는 이유: 출력 상한에 걸려 잘린 응답을 성공으로 처리하면
    A6 리라이팅 결과가 문장 중간에서 끊긴 채 사용자에게 간다. 호출자가 알아야 한다.
    """

    text: str
    usage: Usage
    stop_reason: str = "stop"
    latency_ms: int = 0

    @property
    def truncated(self) -> bool:
        return self.stop_reason == "length"

    def __repr__(self) -> str:
        return (
            f"LlmResponse(text={len(self.text)}자, usage={self.usage}, "
            f"stop_reason={self.stop_reason!r}, latency_ms={self.latency_ms})"
        )


# --------------------------------------------------------------------------
# 제공자 포트
# --------------------------------------------------------------------------

class LlmProvider(Protocol):
    """모델 제공자. 제공자가 정해지면 이 프로토콜을 구현한 어댑터를 만든다.

    구현 측 계약:
      - 실패는 ``errors.py`` 의 예외로 변환해 던진다. SDK 예외를 그대로 올리지 않는다.
        무엇이 재시도 대상인지는 제공자만 알고, 그 판단을 여기서 타입으로 고정한다.
      - ``timeout_s`` 를 지킨다. 지키지 않아도 클라이언트가 한 겹 더 막는다.
      - 자격증명은 어댑터가 들고 있는다. 클라이언트는 키를 모른다.
    """

    @property
    def model_id(self) -> str: ...

    async def generate(self, request: LlmRequest, *, timeout_s: float) -> LlmResponse: ...


class NotConfiguredProvider:
    """제공자가 정해지기 전의 기본값.

    import 는 되고 호출만 실패한다. 덕분에 A5·A6·A8을 미리 작성하고 테스트까지
    할 수 있다 — 테스트는 가짜 제공자를 주입한다.
    """

    @property
    def model_id(self) -> str:
        return "unconfigured"

    async def generate(self, request: LlmRequest, *, timeout_s: float) -> LlmResponse:
        raise LlmUnavailable(
            "LLM 제공자가 설정되지 않았습니다. 제공자·모델 확정 후 어댑터를 주입하십시오."
        )


# --------------------------------------------------------------------------
# 재시도 정책
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RetryPolicy:
    """지수 백오프 + 지터.

    지터를 넣는 이유: 여러 요청이 같은 순간에 제한에 걸리면 재시도도 같은 순간에
    몰려 다시 제한에 걸린다.
    """

    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    jitter_ratio: float = 0.25

    def delay_for(self, attempt: int, *, rand: float) -> float:
        """``attempt`` 는 1부터. ``rand`` 는 0~1 난수 (테스트에서 고정하기 위해 인자로 받는다)."""
        raw = min(self.base_delay_s * (2 ** (attempt - 1)), self.max_delay_s)
        return raw * (1.0 + self.jitter_ratio * (rand * 2 - 1))


# --------------------------------------------------------------------------
# 클라이언트
# --------------------------------------------------------------------------

@dataclass
class LlmClient:
    """타임아웃·재시도·호출 상한·토큰 계측을 한 곳에서 처리한다.

    provider 를 인자로 받는 이유: 제공자가 미정이고, 테스트에서 가짜를 넣어야 한다.
    """

    provider: LlmProvider = field(default_factory=NotConfiguredProvider)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_calls: int = DEFAULT_MAX_CALLS
    #: 한 요청의 총 토큰 상한. None 이면 호출 수 상한만 적용한다.
    max_total_tokens: int | None = None

    # 테스트에서 실제로 기다리지 않도록 주입 가능하게 둔다
    _sleep: object = field(default=None, repr=False)
    _rand: object = field(default=None, repr=False)

    async def _wait(self, seconds: float) -> None:
        sleep = self._sleep or asyncio.sleep
        await sleep(seconds)  # type: ignore[operator]

    def _random(self) -> float:
        rand = self._rand or random.random
        return rand()  # type: ignore[operator]

    # ------------------------------------------------------------------ 단일 호출

    async def generate(self, request: LlmRequest) -> LlmResponse:
        """한 번 호출한다. 실패하면 정책에 따라 재시도한다.

        재시도는 **재시도 가능 예외일 때만** 한다. 잘못된 요청을 세 번 보내면
        세 배로 틀리는 것뿐이다.
        """
        last: LlmRetryable | None = None

        for attempt in range(1, self.retry.max_attempts + 1):
            started = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    self.provider.generate(request, timeout_s=self.timeout_s),
                    # 어댑터가 timeout_s 를 무시해도 여기서 끊는다
                    timeout=self.timeout_s,
                )
            except TimeoutError as exc:
                last = LlmTimeout(f"{self.timeout_s}초 안에 응답이 없었습니다")
                last.__cause__ = exc
            except LlmRetryable as exc:
                last = exc
            else:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                # 어댑터가 지연을 채우지 않았으면 우리가 측정한 값을 넣는다
                return response if response.latency_ms else replace(
                    response, latency_ms=elapsed_ms
                )

            if attempt == self.retry.max_attempts:
                break

            delay = (
                last.retry_after_s
                if isinstance(last, LlmThrottled) and last.retry_after_s is not None
                else self.retry.delay_for(attempt, rand=self._random())
            )
            await self._wait(delay)

        assert last is not None  # 루프는 성공 아니면 예외로만 끝난다
        raise last

    # ------------------------------------------------------------------ 분할 호출

    async def generate_split(self, requests: Sequence[LlmRequest]) -> tuple[list[LlmResponse], Usage]:
        """긴 입력을 나눠 보낸다 (A6의 5,000자 초과 분할).

        ★ 상한 검사를 **호출 전에** 한다. 세 번 부른 뒤 네 번째에서 거절하면
          토큰은 이미 썼고 결과는 버려진다.

        반환값의 두 번째가 **합산된 사용량**이다. 호출자는 이 값 하나만
        C7 쿼터와 B11 감사 로그에 넘긴다.
        """
        if not requests:
            return [], ZERO_USAGE

        if len(requests) > self.max_calls:
            raise LlmBudgetExceeded(
                f"분할 호출 {len(requests)}회는 상한 {self.max_calls}회를 넘습니다"
            )

        responses: list[LlmResponse] = []
        total = ZERO_USAGE

        for request in requests:
            response = await self.generate(request)
            responses.append(response)
            total = total + response.usage

            if self.max_total_tokens is not None and total.total_tokens > self.max_total_tokens:
                # 이미 쓴 토큰은 되돌릴 수 없다. 더 쓰지 않고 멈추는 것이 전부다.
                raise LlmBudgetExceeded(
                    f"토큰 {total.total_tokens}개는 상한 {self.max_total_tokens}개를 넘습니다"
                )

        return responses, total


def validate_request(request: LlmRequest) -> None:
    """보내기 전에 거를 수 있는 것은 거른다. 제공자까지 갈 필요가 없다."""
    if not request.prompt.strip():
        raise LlmInvalidRequest("프롬프트가 비어 있습니다")
    if request.max_output_tokens <= 0:
        raise LlmInvalidRequest("max_output_tokens 는 1 이상이어야 합니다")
    if not 0.0 <= request.temperature <= 2.0:
        raise LlmInvalidRequest("temperature 는 0.0~2.0 범위여야 합니다")
