"""NeMo Guardrails 의도 판정(C16). 순수 판정만 — 파이프라인 연결·감사 로그 기록은 하지 않는다.

- 임베딩: 우리 `Embedder`(bge-m3, TEI)를 NeMo 공급자 `nesume_bge_m3` 로 꽂는다. 기본 FastEmbed 를 쓰지 않는다.
- 의도 → 판정: 권한 외 `flag`, 탈취 `block`, 문서 속 지시문 `drop`(그 조각 제외), 그 밖 `allow`.
- 실패(임베더 장애·NeMo 오류)는 호출부가 fail-open 으로 다룬다 — 여기서는 예외를 그대로 올린다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.retrieval.embedder import Embedder

CONFIG_DIR = Path(__file__).with_name("config")
ENGINE = "nesume_bge_m3"
#: NeMo 점수(1 - 각거리/2, 0.6 ≈ 코사인 0.68) 하한.
#: 비교표(docs/C16.md)에서 정상 50건 차단 0을 지키는 가장 낮은 값
DEFAULT_THRESHOLD = 0.6

Intent = Literal["authz", "exfil", "instruction", "normal"]
Action = Literal["allow", "flag", "block", "drop"]

ACTION: dict[Intent, Action] = {"authz": "flag", "exfil": "block", "instruction": "drop", "normal": "allow"}
_PREFIX = "NEMO_INTENT:"

# NeMo 가 공급자 클래스를 이름으로 만들기 때문에 인스턴스를 넘길 자리가 없다. 만들기 직전에 여기 둔다
_current_embedder: Embedder | None = None


@dataclass(frozen=True)
class NemoResult:
    intent: Intent

    @property
    def action(self) -> Action:
        return ACTION[self.intent]

    @property
    def rule_id(self) -> str | None:
        return None if self.intent == "normal" else f"NEMO_INTENT_{self.intent.upper()}"


_registered = False


def _register_provider() -> None:
    global _registered
    if _registered:  # NeMo 레지스트리는 같은 이름을 두 번 받지 않는다
        return
    from nemoguardrails.embeddings.providers import register_embedding_provider
    from nemoguardrails.embeddings.providers.base import EmbeddingModel

    class NesumeBgeM3(EmbeddingModel):
        engine_name = ENGINE

        def __init__(self, embedding_model: str, **kwargs):
            if _current_embedder is None:
                raise RuntimeError("C16: 임베더가 없다")
            self._embedder = _current_embedder

        def encode(self, documents: list[str]) -> list[list[float]]:
            return self._embedder.embed(list(documents))

        async def encode_async(self, documents: list[str]) -> list[list[float]]:
            return await asyncio.to_thread(self.encode, documents)

    register_embedding_provider(NesumeBgeM3, ENGINE)
    _registered = True


def parse_intent(content: str) -> Intent:
    """봇 문구 → 의도. 모르는 문구는 normal(올리지 않는다)."""
    if content.startswith(_PREFIX):
        name = content[len(_PREFIX):].strip()
        if name in ACTION:
            return name  # type: ignore[return-value]
    return "normal"


class NemoIntentRail:
    """설정(config/) + 임베더로 만든 의도 판정기. 만들 때 예시 문장을 한 번 임베딩한다."""

    def __init__(
        self, embedder: Embedder, *, threshold: float = DEFAULT_THRESHOLD, config_dir: Path = CONFIG_DIR
    ):
        global _current_embedder
        from nemoguardrails import LLMRails, RailsConfig

        _register_provider()
        config = RailsConfig.from_path(str(config_dir))
        config.rails.dialog.user_messages.embeddings_only_similarity_threshold = threshold
        _current_embedder = embedder
        self.threshold = threshold
        self._rails = LLMRails(config)

    async def acheck(self, text: str) -> NemoResult:
        res = await self._rails.generate_async(messages=[{"role": "user", "content": text}])
        return NemoResult(parse_intent(str(res.get("content", ""))))

    def check_many(self, texts: list[str]) -> list[NemoResult]:
        async def run() -> list[NemoResult]:
            return [await self.acheck(t) for t in texts]

        return asyncio.run(run())
