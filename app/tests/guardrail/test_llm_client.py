"""A2 LLM 클라이언트 단위 테스트.

DB도 네트워크도 쓰지 않는다. 제공자는 가짜를 주입한다.
"""

from __future__ import annotations

import pytest

from app.guardrail import (
    DEFAULT_MAX_CALLS,
    ZERO_USAGE,
    LlmBudgetExceeded,
    LlmClient,
    LlmInvalidRequest,
    LlmRequest,
    LlmThrottled,
    LlmTimeout,
    LlmTransient,
    LlmUnavailable,
    NotConfiguredProvider,
    RetryPolicy,
    Usage,
    validate_request,
)
from tests.guardrail.fakes import FakeProvider, HangingProvider, SleepRecorder


def _client(provider, **kwargs) -> LlmClient:
    """재시도 대기를 기록만 하는 클라이언트. 테스트가 실제로 멈추지 않는다."""
    kwargs.setdefault("_sleep", SleepRecorder())
    kwargs.setdefault("_rand", lambda: 0.5)  # 지터 고정 → 대기 시간이 결정적
    return LlmClient(provider=provider, **kwargs)


# ---------------------------------------------------------------- 정상 호출

@pytest.mark.anyio
async def test_generate_returns_text_and_usage() -> None:
    provider = FakeProvider(reply="안녕하세요", input_tokens=12, output_tokens=7)
    response = await _client(provider).generate(LlmRequest(prompt="자소서를 다듬어 주세요"))

    assert response.text == "안녕하세요"
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 7
    assert response.usage.total_tokens == 19
    assert response.usage.calls == 1
    assert response.usage.model == "fake-model-1"
    assert len(provider.calls) == 1


@pytest.mark.anyio
async def test_timeout_is_passed_to_provider() -> None:
    provider = FakeProvider()
    await _client(provider, timeout_s=12.5).generate(LlmRequest(prompt="x"))
    assert provider.timeouts == [12.5]


@pytest.mark.anyio
async def test_latency_is_filled_when_provider_omits_it() -> None:
    """어댑터가 지연을 채우지 않아도 호출자는 측정값을 받는다."""
    response = await _client(FakeProvider(latency_ms=0)).generate(LlmRequest(prompt="x"))
    assert response.latency_ms >= 0
    assert isinstance(response.latency_ms, int)


@pytest.mark.anyio
async def test_provider_latency_is_kept() -> None:
    response = await _client(FakeProvider(latency_ms=777)).generate(LlmRequest(prompt="x"))
    assert response.latency_ms == 777


@pytest.mark.anyio
async def test_truncated_is_reported() -> None:
    """출력 상한에 걸려 잘린 응답을 성공으로 숨기지 않는다."""
    response = await _client(FakeProvider(stop_reason="length")).generate(LlmRequest(prompt="x"))
    assert response.truncated is True


# ---------------------------------------------------------------- 재시도

@pytest.mark.anyio
async def test_retries_then_succeeds() -> None:
    provider = FakeProvider(failures=[LlmTransient("일시 장애"), LlmTimeout("느림")])
    response = await _client(provider).generate(LlmRequest(prompt="x"))

    assert response.text == "응답입니다"
    assert len(provider.calls) == 3  # 실패 2 + 성공 1


@pytest.mark.anyio
async def test_gives_up_after_max_attempts() -> None:
    provider = FakeProvider(failures=[LlmTransient("1"), LlmTransient("2"), LlmTransient("3")])
    client = _client(provider, retry=RetryPolicy(max_attempts=3))

    with pytest.raises(LlmTransient):
        await client.generate(LlmRequest(prompt="x"))

    assert len(provider.calls) == 3


@pytest.mark.anyio
async def test_invalid_request_is_not_retried() -> None:
    """잘못된 요청을 세 번 보내면 세 배로 틀리는 것뿐이다."""
    provider = FakeProvider(failures=[LlmInvalidRequest("모델 이름 오류")])

    with pytest.raises(LlmInvalidRequest):
        await _client(provider).generate(LlmRequest(prompt="x"))

    assert len(provider.calls) == 1


@pytest.mark.anyio
async def test_throttle_retry_after_is_respected() -> None:
    """제공자가 알려준 대기 시간이 우리 백오프 계산보다 정확하다."""
    sleeper = SleepRecorder()
    provider = FakeProvider(failures=[LlmThrottled("제한", retry_after_s=2.5)])
    client = _client(provider, _sleep=sleeper)

    await client.generate(LlmRequest(prompt="x"))
    assert sleeper.waits == [2.5]


@pytest.mark.anyio
async def test_backoff_grows_and_is_capped() -> None:
    sleeper = SleepRecorder()
    provider = FakeProvider(failures=[LlmTransient("1"), LlmTransient("2")])
    client = _client(
        provider,
        retry=RetryPolicy(max_attempts=3, base_delay_s=1.0, max_delay_s=1.5, jitter_ratio=0.0),
        _sleep=sleeper,
    )

    await client.generate(LlmRequest(prompt="x"))
    assert sleeper.waits == [1.0, 1.5]  # 2.0이 아니라 상한 1.5


def test_retry_policy_delay_is_bounded() -> None:
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=4.0, jitter_ratio=0.25)
    for attempt in range(1, 8):
        for rand in (0.0, 0.5, 1.0):
            delay = policy.delay_for(attempt, rand=rand)
            assert 0.0 <= delay <= 4.0 * 1.25


@pytest.mark.anyio
async def test_client_cuts_off_a_hanging_provider() -> None:
    """어댑터가 timeout_s 를 무시해도 요청이 영구히 매달리지 않는다."""
    client = _client(HangingProvider(), timeout_s=0.01, retry=RetryPolicy(max_attempts=1))

    with pytest.raises(LlmTimeout):
        await client.generate(LlmRequest(prompt="x"))


# ---------------------------------------------------------------- 분할 호출

@pytest.mark.anyio
async def test_split_sums_usage() -> None:
    """호출자는 합산된 사용량 하나만 C7·B11에 넘긴다."""
    provider = FakeProvider(input_tokens=10, output_tokens=4)
    requests = [LlmRequest(prompt=f"{i}") for i in range(3)]

    responses, usage = await _client(provider).generate_split(requests)

    assert len(responses) == 3
    assert usage.calls == 3
    assert usage.input_tokens == 30
    assert usage.output_tokens == 12
    assert usage.total_tokens == 42


@pytest.mark.anyio
async def test_split_limit_rejects_before_calling() -> None:
    """★ 상한 검사는 호출 전에. 세 번 부른 뒤 거절하면 토큰은 이미 썼다."""
    provider = FakeProvider()
    client = _client(provider, max_calls=2)

    with pytest.raises(LlmBudgetExceeded):
        await client.generate_split([LlmRequest(prompt="x")] * 3)

    assert provider.calls == [], "거절 전에 제공자를 불렀다"


@pytest.mark.anyio
async def test_split_at_limit_is_allowed() -> None:
    provider = FakeProvider()
    client = _client(provider, max_calls=2)
    responses, usage = await client.generate_split([LlmRequest(prompt="x")] * 2)
    assert len(responses) == 2
    assert usage.calls == 2


@pytest.mark.anyio
async def test_empty_split_does_not_call_provider() -> None:
    provider = FakeProvider()
    responses, usage = await _client(provider).generate_split([])
    assert responses == []
    assert usage == ZERO_USAGE
    assert provider.calls == []


@pytest.mark.anyio
async def test_token_budget_stops_further_calls() -> None:
    provider = FakeProvider(input_tokens=10, output_tokens=10)
    client = _client(provider, max_total_tokens=25)

    with pytest.raises(LlmBudgetExceeded):
        await client.generate_split([LlmRequest(prompt="x")] * 3)

    assert len(provider.calls) == 2, "상한을 넘긴 직후 멈춰야 한다"


def test_default_max_calls_is_conservative() -> None:
    assert DEFAULT_MAX_CALLS <= 8, "상한이 느슨하면 호출 수가 입력 길이에 따라 늘어난다"


# ---------------------------------------------------------------- 사용량 합산

def test_usage_add() -> None:
    a = Usage(input_tokens=1, output_tokens=2, model="m")
    b = Usage(input_tokens=10, output_tokens=20, model="m")
    total = a + b
    assert (total.input_tokens, total.output_tokens, total.calls) == (11, 22, 2)
    assert total.model == "m"


def test_usage_add_marks_mixed_models() -> None:
    """모델이 섞이면 합산값의 의미가 달라진다. 섞인 사실을 숨기지 않는다."""
    total = Usage(1, 1, "a") + Usage(1, 1, "b")
    assert "a" in total.model and "b" in total.model


def test_zero_usage_is_identity() -> None:
    u = Usage(input_tokens=3, output_tokens=4, model="m")
    assert (ZERO_USAGE + u).total_tokens == u.total_tokens
    assert (ZERO_USAGE + u).calls == 1


# ---------------------------------------------------------------- 유출 방지

def test_request_repr_hides_prompt() -> None:
    """프롬프트에는 토큰화가 놓친 PII가 섞일 수 있다. 스택트레이스로 새면 안 된다."""
    request = LlmRequest(prompt="연락처는 010-1234-5678 입니다", system="비밀 지침")
    text = repr(request)

    assert "010-1234-5678" not in text
    assert "비밀 지침" not in text
    assert "자" in text  # 길이만 남는다


@pytest.mark.anyio
async def test_response_repr_hides_text() -> None:
    response = await _client(FakeProvider(reply="김철수님께")).generate(LlmRequest(prompt="x"))
    assert "김철수" not in repr(response)


# ---------------------------------------------------------------- 제공자 미정

@pytest.mark.anyio
async def test_unconfigured_provider_raises_on_call_not_on_import() -> None:
    """제공자 미정이어도 import·조립은 된다. 호출만 막힌다."""
    client = LlmClient()  # 기본값 = NotConfiguredProvider
    assert isinstance(client.provider, NotConfiguredProvider)

    with pytest.raises(LlmUnavailable):
        await client.generate(LlmRequest(prompt="x"))


@pytest.mark.anyio
async def test_unavailable_is_not_retried() -> None:
    """설정이 없는 상태로 세 번 부르는 것은 의미가 없다."""
    provider = NotConfiguredProvider()
    with pytest.raises(LlmUnavailable):
        await _client(provider).generate(LlmRequest(prompt="x"))


# ---------------------------------------------------------------- 요청 검증

@pytest.mark.parametrize(
    "request_",
    [
        LlmRequest(prompt="   "),
        LlmRequest(prompt="x", max_output_tokens=0),
        LlmRequest(prompt="x", temperature=-0.1),
        LlmRequest(prompt="x", temperature=2.5),
    ],
)
def test_validate_request_rejects(request_: LlmRequest) -> None:
    with pytest.raises(LlmInvalidRequest):
        validate_request(request_)


def test_validate_request_accepts_normal() -> None:
    validate_request(LlmRequest(prompt="자소서를 다듬어 주세요"))
