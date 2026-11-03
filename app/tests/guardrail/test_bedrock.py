"""A2 Bedrock 어댑터 단위 테스트.

네트워크를 쓰지 않는다. botocore Stubber 로 Converse 응답·오류를 흉내 낸다.
"""

from __future__ import annotations

from types import SimpleNamespace

import boto3
import pytest
from botocore.stub import Stubber

from app.guardrail import (
    LlmClient,
    LlmInvalidRequest,
    LlmRequest,
    LlmThrottled,
    LlmTransient,
    LlmUnavailable,
    NotConfiguredProvider,
)
from app.guardrail.bedrock import BedrockProvider, build_provider
from tests.guardrail.fakes import SleepRecorder

MODEL = "global.amazon.nova-2-lite-v1:0"


def _stubbed() -> tuple[BedrockProvider, Stubber]:
    client = boto3.client(
        "bedrock-runtime", region_name="ap-northeast-2",
        aws_access_key_id="x", aws_secret_access_key="x",
    )
    return BedrockProvider(MODEL, client=client), Stubber(client)


def _ok(text: str = "고친 문장", stop: str = "end_turn") -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": stop,
        "usage": {"inputTokens": 30, "outputTokens": 7, "totalTokens": 37},
        "metrics": {"latencyMs": 420},
    }


@pytest.mark.anyio
async def test_converse_maps_text_usage_and_system() -> None:
    provider, stub = _stubbed()
    stub.add_response("converse", _ok(), {
        "modelId": MODEL,
        "messages": [{"role": "user", "content": [{"text": "글"}]}],
        "system": [{"text": "규칙"}],
        "inferenceConfig": {"maxTokens": 100, "temperature": 0.3},
    })
    with stub:
        resp = await provider.generate(
            LlmRequest(prompt="글", system="규칙", max_output_tokens=100), timeout_s=5
        )

    assert resp.text == "고친 문장"
    assert resp.usage.input_tokens == 30 and resp.usage.output_tokens == 7
    assert resp.usage.model == MODEL
    assert resp.latency_ms == 420
    assert not resp.truncated


@pytest.mark.anyio
async def test_max_tokens_is_reported_as_truncated() -> None:
    provider, stub = _stubbed()
    stub.add_response("converse", _ok(stop="max_tokens"))
    with stub:
        resp = await provider.generate(LlmRequest(prompt="글"), timeout_s=5)
    assert resp.truncated


@pytest.mark.anyio
@pytest.mark.parametrize(("code", "status", "expected"), [
    ("ThrottlingException", 429, LlmThrottled),
    ("ServiceUnavailableException", 503, LlmTransient),
    ("AccessDeniedException", 403, LlmUnavailable),
    ("ResourceNotFoundException", 404, LlmUnavailable),
    ("ValidationException", 400, LlmInvalidRequest),
])
async def test_client_errors_map_to_our_types(code: str, status: int, expected: type) -> None:
    provider, stub = _stubbed()
    stub.add_client_error("converse", service_error_code=code, http_status_code=status)
    with stub, pytest.raises(expected):
        await provider.generate(LlmRequest(prompt="글"), timeout_s=5)


@pytest.mark.anyio
async def test_throttle_is_retried_by_llm_client() -> None:
    """재시도는 LlmClient 한 겹만. 어댑터는 오류를 타입으로만 바꾼다."""
    provider, stub = _stubbed()
    stub.add_client_error("converse", service_error_code="ThrottlingException", http_status_code=429)
    stub.add_response("converse", _ok("두 번째"))
    client = LlmClient(provider=provider, _sleep=SleepRecorder(), _rand=lambda: 0.5)
    with stub:
        resp = await client.generate(LlmRequest(prompt="글"))
    assert resp.text == "두 번째"


def test_build_provider_defaults_to_not_configured() -> None:
    assert isinstance(build_provider(SimpleNamespace(llm_provider="none")), NotConfiguredProvider)


def test_build_provider_bedrock_pins_real_endpoint() -> None:
    """compose 의 AWS_ENDPOINT_URL(LocalStack)로 새지 않아야 한다."""
    settings = SimpleNamespace(
        llm_provider="bedrock", llm_model_id=MODEL, bedrock_region="ap-northeast-2",
        bedrock_access_key_id="x", bedrock_secret_access_key="x", bedrock_session_token=None,
    )
    provider = build_provider(settings)
    assert isinstance(provider, BedrockProvider)
    assert provider.model_id == MODEL
    assert provider._client.meta.endpoint_url == "https://bedrock-runtime.ap-northeast-2.amazonaws.com"
