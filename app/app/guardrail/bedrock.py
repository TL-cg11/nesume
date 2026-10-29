"""A2 제공자 어댑터 — Amazon Bedrock Converse API.

`llm_client.py` 의 "정해지면 어댑터 한 파일을 추가하고 주입 지점만 바꾼다" 의 그 한 파일이다.
호출부(A6·A7·A8·A13)와 `LlmClient` 는 고치지 않는다.

★ Converse API 를 쓴다. 모델마다 요청 본문이 다른 InvokeModel 과 달리 형식이 하나라
  **모델 교체가 환경변수(LLM_MODEL_ID) 한 줄**이다. 2026-10-28 현재 Anthropic 모델은
  계정 게이트로 거부되어 임시로 Nova 2 Lite 를 쓴다. 열리면 Haiku 5.5 로 바꾼다.

★ 재시도는 여기서 하지 않는다. botocore 재시도를 끄고(`max_attempts=1`) `LlmClient` 의
  백오프 하나만 남긴다. 두 겹이면 3 × 3 = 9번까지 불린다.

★ 엔드포인트를 **명시**한다. 로컬 compose 는 `AWS_ENDPOINT_URL` 을 LocalStack 으로
  두는데, boto3 는 그 값을 모든 서비스에 쓴다. 비워 두면 Bedrock 호출이 LocalStack 으로 간다.
"""

from __future__ import annotations

import asyncio
from typing import Any

from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
)

from app.guardrail.errors import (
    LlmError,
    LlmInvalidRequest,
    LlmThrottled,
    LlmTimeout,
    LlmTransient,
    LlmUnavailable,
)
from app.guardrail.llm_client import (
    DEFAULT_TIMEOUT_S,
    LlmProvider,
    LlmRequest,
    LlmResponse,
    NotConfiguredProvider,
    Usage,
)

#: 제공자 오류 코드 → 우리 예외. 재시도 여부를 여기서 타입으로 고정한다.
_THROTTLED = {"ThrottlingException", "ServiceQuotaExceededException", "TooManyRequestsException"}
_TIMEOUT = {"ModelTimeoutException"}
_TRANSIENT = {
    "InternalServerException", "ServiceUnavailableException", "ModelNotReadyException",
}
#: ★ 권한·모델 접근 문제는 **미연결**로 본다. 기능들이 `LlmUnavailable` 만 잡아
#:   규칙 결과로 내려가므로, 사용자는 500 대신 "AI 를 쓸 수 없음" 안내를 받는다.
_UNAVAILABLE = {
    "AccessDeniedException", "ResourceNotFoundException", "UnrecognizedClientException",
    "ExpiredTokenException", "InvalidSignatureException",
}


def _map_client_error(exc: ClientError) -> LlmError:
    code = exc.response.get("Error", {}).get("Code", "")
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
    # 메시지에는 프롬프트가 들어가지 않는다(오류 코드·모델 ID 정도). 그래도 길이는 자른다
    message = f"Bedrock {code or status}: {str(exc)[:200]}"

    if code in _THROTTLED:
        return LlmThrottled(message)
    if code in _TIMEOUT:
        return LlmTimeout(message)
    if code in _UNAVAILABLE:
        return LlmUnavailable(message)
    if code in _TRANSIENT or status >= 500:
        return LlmTransient(message)
    return LlmInvalidRequest(message)


class BedrockProvider:
    """`LlmProvider` 구현. 자격증명은 boto3 클라이언트가 들고 있고 우리는 모른다."""

    def __init__(self, model_id: str, *, client: Any) -> None:
        self._model_id = model_id
        self._client = client

    @property
    def model_id(self) -> str:
        return self._model_id

    def _converse_kwargs(self, request: LlmRequest) -> dict[str, Any]:
        inference: dict[str, Any] = {
            "maxTokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
        if request.stop:
            inference["stopSequences"] = list(request.stop)
        kwargs: dict[str, Any] = {
            "modelId": self._model_id,
            "messages": [{"role": "user", "content": [{"text": request.prompt}]}],
            "inferenceConfig": inference,
        }
        if request.system:
            kwargs["system"] = [{"text": request.system}]
        return kwargs

    async def generate(self, request: LlmRequest, *, timeout_s: float) -> LlmResponse:
        # boto3 는 동기다. 스레드로 넘겨 이벤트 루프를 막지 않는다.
        # timeout_s 는 클라이언트 생성 시 read_timeout 으로 이미 걸려 있다
        try:
            resp = await asyncio.to_thread(self._client.converse, **self._converse_kwargs(request))
        except ClientError as exc:
            raise _map_client_error(exc) from None
        except NoCredentialsError:
            raise LlmUnavailable("Bedrock 자격증명이 없습니다") from None
        except ReadTimeoutError:
            raise LlmTimeout("Bedrock 응답 대기 시간 초과") from None
        except (ConnectTimeoutError, EndpointConnectionError):
            raise LlmTransient("Bedrock 엔드포인트에 연결하지 못했습니다") from None
        except BotoCoreError as exc:
            raise LlmTransient(f"Bedrock 호출 실패: {type(exc).__name__}") from None

        content = resp.get("output", {}).get("message", {}).get("content", [])
        text = "".join(block.get("text", "") for block in content)
        usage = resp.get("usage", {})
        return LlmResponse(
            text=text,
            usage=Usage(
                input_tokens=usage.get("inputTokens", 0),
                output_tokens=usage.get("outputTokens", 0),
                model=self._model_id,
            ),
            # LlmResponse.truncated 가 "length" 를 본다. 이름만 맞춘다
            stop_reason="length" if resp.get("stopReason") == "max_tokens" else "stop",
            latency_ms=resp.get("metrics", {}).get("latencyMs", 0),
        )


def build_provider(settings: Any) -> LlmProvider:
    """설정으로 제공자를 고른다. `none` 이면 기존처럼 호출 시 `LlmUnavailable` 이다."""
    if settings.llm_provider != "bedrock":
        return NotConfiguredProvider()

    import boto3  # 미설정 환경(테스트 등)에서 import 비용을 내지 않는다

    region = settings.bedrock_region
    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        endpoint_url=f"https://bedrock-runtime.{region}.amazonaws.com",
        # 비어 있으면 None → 기본 자격증명 체인(EKS 는 IRSA)
        aws_access_key_id=settings.bedrock_access_key_id or None,
        aws_secret_access_key=settings.bedrock_secret_access_key or None,
        aws_session_token=settings.bedrock_session_token or None,
        config=Config(
            connect_timeout=5,
            read_timeout=DEFAULT_TIMEOUT_S,
            retries={"max_attempts": 1, "mode": "standard"},
        ),
    )
    return BedrockProvider(settings.llm_model_id, client=client)


__all__ = ["BedrockProvider", "build_provider"]
