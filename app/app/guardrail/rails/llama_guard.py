"""D19 — Llama Guard(Bedrock) 출력 레일. A5 출력 검사 **뒤**, 복원(detokenize) **앞**에서 응답을 한 번 더
본다.

A5 는 규칙(카나리·시스템 프롬프트·PII·토큰)으로 유출을 잡고, 이 레일은 **범용 유해
콘텐츠**(폭력·무기·자해·혐오·
성적 내용 등 Llama Guard 3 의 13개 범주)를 안전 분류 모델로 잡는다. 자소서 도우미가 그런 응답을 만들 일은
드물지만, 프롬프트 주입으로 모델을 돌렸을 때의 마지막 그물이다.

모델: 이 AWS 계정의 Bedrock 에는 `meta.llama-guard-*` 가 없다(2026-11-03 서울·버지니아·오레곤 카탈로그
확인). 그래서
Llama Guard 3 의 **프롬프트 템플릿과 범주 체계를 그대로 두고** 호출 모델만 설정으로
뺐다(`LLAMA_GUARD_MODEL_ID`).
기본값은 Llama 3.1 8B(버지니아 교차 리전 프로파일, 11-03 실측 ~2.5s)이고, 모델이 열리면 ID 한 줄만 바꾼다.
출력 형식은 Llama Guard 와 같다: 첫 줄 `safe` / `unsafe`, unsafe 면 둘째 줄(또는 같은 줄 쉼표 뒤)에 범주.

판정 (docs/policy/block-policy.md 2장 #15)
    unsafe        → block, stage output_guard, rule_id UNSAFE_CONTENT + 범주별 표식 UNSAFE_CONTENT.S9 …
    safe          → allow
    오류·타임아웃  → fail-open(기본): allow + 표식 OUTRAIL_ERROR(info). LLAMA_GUARD_FAIL_OPEN=false 면 block.
    형식 불명     → 오류와 같이 처리(모델이 지시를 안 따른 것)

비용·지연 가드
    - LLAMA_GUARD_MAX_CHARS: 검사 대상 응답 앞부분만(기본 4000자). 유해 응답은 앞에서 드러나고, 긴 꼬리는
    비용만 든다
    - LLAMA_GUARD_SAMPLE_RATE: 1.0 이면 전부, 0.2 면 요청의 20% 만 검사(비용 조정용). 미검사 요청은 표식
    OUTRAIL_SKIPPED
    - 타임아웃 LLAMA_GUARD_TIMEOUT_S(기본 3s), 재시도 없음. 출력 토큰 상한 32 (판정 한두 줄이면 충분)
    - 쿼터(C7)와 별개로 센다: `nesume.guardrail.rail` 로거에 모델·지연·판정 1줄(원문 없음)

★ 이 파일은 가드레일 패키지 안에 있다(D11 CI 가 바깥의 `bedrock-runtime`·llm_client import 를 막는다).
★ 응답 **원문을 보낸다** — 마스킹·토큰화된 상태(A1 이 원문을 지운 뒤)라 PII 는 모델에 가지 않는다.
"""
from __future__ import annotations

import logging
import random
import re
import time
from typing import Any, Protocol

from app.guardrail.errors import LlmError
from app.guardrail.llm_client import LlmProvider, LlmRequest
from app.guardrail.schema import Finding, Verdict, allow

log = logging.getLogger("nesume.guardrail.rail")

STAGE = "output_guard"
RULE_UNSAFE = "UNSAFE_CONTENT"
RULE_ERROR = "OUTRAIL_ERROR"
RULE_SKIPPED = "OUTRAIL_SKIPPED"

#: Llama Guard 3 범주(MLCommons 위험 분류). 표식은 UNSAFE_CONTENT.<코드> 로 남긴다
CATEGORIES: dict[str, str] = {
    "S1": "Violent Crimes.",
    "S2": "Non-Violent Crimes.",
    "S3": "Sex Crimes.",
    "S4": "Child Exploitation.",
    "S5": "Defamation.",
    "S6": "Specialized Advice.",
    "S7": "Privacy.",
    "S8": "Intellectual Property.",
    "S9": "Indiscriminate Weapons.",
    "S10": "Hate.",
    "S11": "Self-Harm.",
    "S12": "Sexual Content.",
    "S13": "Elections.",
}

_CATEGORY_RE = re.compile(r"\bS(1[0-3]|[1-9])\b")
#: 대역 모델(Llama 3.1 instruct)은 아주 노골적인 본문에는 판정 대신 **거절문**을 낸다
#: ("I can't provide information or guidance on illegal or harmful activities…", 11-03 실측).
#: 분류기가 거절했다는 것 자체가 유해하다는 신호이므로 unsafe 로 본다(범주 표식 `REFUSAL`).
#: 정식 Llama Guard 는 거절하지 않으므로 그때는 이 분기가 돌지 않는다.
_REFUSAL_RE = re.compile(
    r"^(i can(no|')t|i'm (not able|unable)|i am (not able|unable)|i won't|sorry)", re.IGNORECASE
)
REFUSAL_CATEGORY = "REFUSAL"
_MAX_OUTPUT_TOKENS = 32


def build_prompt(agent_text: str, *, user_text: str = "") -> str:
    """Llama Guard 3 의 Agent 메시지 검사 템플릿. 사용자 질의는 **넣지 않는다**(원문을 밖으로 내지 않는다)."""
    cats = "\n".join(f"{k}: {v}" for k, v in CATEGORIES.items())
    return (
        "Task: Check if there is unsafe content in 'Agent' messages in conversations according our safety "
        "policy with the below categories.\n\n"
        f"<BEGIN UNSAFE CONTENT CATEGORIES>\n{cats}\n<END UNSAFE CONTENT CATEGORIES>\n\n"
        "<BEGIN CONVERSATION>\n\n"
        f"User: {user_text or '(자기소개서 작성 도움 요청)'}\n\n"
        f"Agent: {agent_text}\n\n"
        "<END CONVERSATION>\n\n"
        "Provide your safety assessment for ONLY THE LAST Agent message in the above conversation:\n"
        " - First line must read 'safe' or 'unsafe'.\n"
        " - If unsafe, a second line must include a comma-separated list of violated categories. "
        "Output nothing else."
    )


def parse_assessment(text: str) -> tuple[bool, tuple[str, ...]] | None:
    """모델 출력 → (unsafe 인가, 범주들). 형식이 아니면 None.

    Llama Guard 정식은 "unsafe\\nS9", Llama 3.1 대역은 "unsafe, S9, S1" 처럼 같은 줄에 쓰기도 한다. 둘 다
    받는다.
    """
    head = text.strip().lower()
    if not head:
        return None
    first = head.split()[0].strip(",.:;")
    if first == "safe":
        return False, ()
    if first == "unsafe":
        cats = tuple(dict.fromkeys(f"S{m.group(1)}" for m in _CATEGORY_RE.finditer(text.upper())))
        return True, cats
    if _REFUSAL_RE.match(head):
        return True, (REFUSAL_CATEGORY,)
    return None


class OutputRail(Protocol):
    """파이프라인(A8)이 보는 포트. 복원 전 응답 본문을 받아 판정을 돌려준다."""

    async def check(self, text: str) -> Verdict: ...


class LlamaGuardRail:
    """`OutputRail` 구현. 제공자(`LlmProvider`)는 주입받는다 — 테스트는 가짜, 운영은 Bedrock."""

    def __init__(
        self,
        provider: LlmProvider,
        *,
        timeout_s: float = 3.0,
        max_chars: int = 4000,
        sample_rate: float = 1.0,
        fail_open: bool = True,
        rng: random.Random | None = None,
    ) -> None:
        self._provider = provider
        self._timeout = timeout_s
        self._max_chars = max(1, max_chars)
        self._sample_rate = min(1.0, max(0.0, sample_rate))
        self._fail_open = fail_open
        self._rng = rng or random.Random()

    @property
    def model_id(self) -> str:
        return self._provider.model_id

    async def check(self, text: str) -> Verdict:
        if not text.strip():
            return allow(STAGE)
        if self._sample_rate < 1.0 and self._rng.random() >= self._sample_rate:
            return Verdict("allow", STAGE, (Finding(RULE_SKIPPED, "info"),))

        request = LlmRequest(
            prompt=build_prompt(text[: self._max_chars]),
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            temperature=0.0,
        )
        started = time.monotonic()
        try:
            response = await self._provider.generate(request, timeout_s=self._timeout)
        except LlmError as exc:
            return self._failed("provider_error", type(exc).__name__, started)
        except Exception as exc:  # noqa: BLE001 - 레일 오류가 요청을 깨면 안 된다(fail-open 정책)
            return self._failed("unexpected", type(exc).__name__, started)

        parsed = parse_assessment(response.text)
        if parsed is None:
            return self._failed("unparseable", response.text[:40], started)
        unsafe, cats = parsed
        self._log("unsafe" if unsafe else "safe", started, categories=",".join(cats) or "-",
                  tokens=response.usage.total_tokens)
        if not unsafe:
            return allow(STAGE)
        by_category = (Finding(f"{RULE_UNSAFE}.{c}", "critical") for c in cats)
        findings = (Finding(RULE_UNSAFE, "critical"), *by_category)
        return Verdict("block", STAGE, findings)

    def _failed(self, why: str, detail: str, started: float) -> Verdict:
        self._log("error", started, why=why, detail=detail, fail_open=self._fail_open)
        if self._fail_open:
            return Verdict("allow", STAGE, (Finding(RULE_ERROR, "info"),))
        return Verdict("block", STAGE, (Finding(RULE_ERROR, "critical"),))

    def _log(self, outcome: str, started: float, **fields: Any) -> None:
        log.info(
            "output_rail",
            extra={"fields": {"rail": "llama_guard", "model": self.model_id, "outcome": outcome,
                              "latency_ms": int((time.monotonic() - started) * 1000), **fields}},
        )


def build_output_rail(settings: Any) -> OutputRail | None:
    """설정으로 레일을 만든다. 꺼져 있으면 None(= A5 만, 기존 동작)."""
    if not getattr(settings, "llama_guard_enabled", False):
        return None

    import boto3  # 켜진 환경에서만 import 비용을 낸다
    from botocore.config import Config

    from app.guardrail.bedrock import BedrockProvider

    region = settings.llama_guard_region
    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        # 로컬 compose 의 AWS_ENDPOINT_URL(LocalStack)이 Bedrock 으로 새지 않게 명시(bedrock.py 와 같은 이유)
        endpoint_url=f"https://bedrock-runtime.{region}.amazonaws.com",
        aws_access_key_id=settings.bedrock_access_key_id or None,
        aws_secret_access_key=settings.bedrock_secret_access_key or None,
        aws_session_token=settings.bedrock_session_token or None,
        config=Config(
            connect_timeout=2,
            read_timeout=settings.llama_guard_timeout_s,
            retries={"max_attempts": 1, "mode": "standard"},
        ),
    )
    return LlamaGuardRail(
        BedrockProvider(settings.llama_guard_model_id, client=client),
        timeout_s=settings.llama_guard_timeout_s,
        max_chars=settings.llama_guard_max_chars,
        sample_rate=settings.llama_guard_sample_rate,
        fail_open=settings.llama_guard_fail_open,
    )


__all__ = [
    "CATEGORIES",
    "RULE_ERROR",
    "RULE_SKIPPED",
    "RULE_UNSAFE",
    "LlamaGuardRail",
    "OutputRail",
    "build_output_rail",
    "build_prompt",
    "parse_assessment",
]
