"""C16 NeMo 레일 — 가드레일 파이프라인의 `InputRail` 포트 구현(pipeline.py).

- 모드: ``shadow``(판정을 바꾸지 않고 로그만 — 파이프라인이 기다리지 않는다) / ``enforce``(판정에 합친다)
  / ``off``.
  질의와 검색 조각을 따로 정한다(`NEMO_QUERY_MODE`, `NEMO_CHUNK_MODE`). 기본은 둘 다 off.
- 올리기만 한다: 탈취·지시문 → block, 권한 외 → allow + 표식. A3 가 막은 것을 풀지 않는다(merge 가 보장).
- 오류·시간 초과는 fail-open — allow + `NEMO_ERROR`(info). 1차 방어(A3)는 그대로 있다.
- 로그: ``nesume.guardrail.rail`` 에 ``nemo_rail`` 한 줄(질의 원문 없음 — 의도·모드·지연만).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from typing import Any, Literal

from app.guardrail.pipeline import Chunk
from app.guardrail.schema import Finding, Verdict
from app.guardrails_nemo.intent import NemoIntentRail, NemoResult

log = logging.getLogger("nesume.guardrail.rail")

Mode = Literal["off", "shadow", "enforce"]
MODES: tuple[Mode, ...] = ("off", "shadow", "enforce")
RULE_ERROR = "NEMO_ERROR"


class NemoRail:
    def __init__(self, intents: Any, *, query_mode: Mode, chunk_mode: Mode, timeout_s: float = 3.0):
        if query_mode not in MODES or chunk_mode not in MODES:
            raise ValueError(f"NeMo 모드는 {MODES} 중 하나여야 한다")
        self._intents = intents  # NemoIntentRail(또는 같은 acheck 를 가진 가짜)
        self.query_mode: Mode = query_mode
        self.chunk_mode: Mode = chunk_mode
        self._timeout_s = timeout_s

    def _timeout(self) -> float:
        # 첫 호출은 예시 색인을 만든다(로컬 2.6초). 그때만 넉넉히 — shadow 면 아무도 기다리지 않는다
        return self._timeout_s if getattr(self._intents, "_ready", True) else max(self._timeout_s, 30.0)

    async def check_query(self, text: str, request_id: str = "") -> Verdict:
        started = time.monotonic()
        try:
            res: NemoResult = await asyncio.wait_for(self._intents.acheck(text), self._timeout())
        except Exception as e:  # noqa: BLE001 - 2차 보강이 요청을 깨면 안 된다(fail-open)
            self._log("query", self.query_mode, "error", started, request_id, error=type(e).__name__)
            return Verdict("allow", "classifier", (Finding(RULE_ERROR, "info"),))
        self._log("query", self.query_mode, res.intent, started, request_id)
        if res.intent in ("exfil", "instruction"):
            return Verdict("block", "classifier", (Finding(res.rule_id or RULE_ERROR, "critical"),),
                           query_type="exfiltration")
        if res.intent == "authz":
            return Verdict("allow", "classifier", (Finding(res.rule_id or RULE_ERROR, "warn"),))
        return Verdict("allow", "classifier")

    async def check_chunks(
        self, chunks: Sequence[Chunk], request_id: str = ""
    ) -> tuple[Sequence[Chunk], Verdict]:
        """지시문 의도로 판정된 조각을 뺀다. 판정은 allow + 표식(뺀 개수) — 나머지로 계속 답한다."""
        started = time.monotonic()
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*(self._intents.acheck(c.text) for c in chunks)), self._timeout()
            )
        except Exception as e:  # noqa: BLE001 - fail-open: 조각을 그대로 둔다
            self._log("chunks", self.chunk_mode, "error", started, request_id, error=type(e).__name__)
            return chunks, Verdict("allow", "retriever", (Finding(RULE_ERROR, "info"),))
        kept = [c for c, r in zip(chunks, results, strict=True) if r.intent != "instruction"]
        dropped = len(chunks) - len(kept)
        self._log("chunks", self.chunk_mode, f"dropped={dropped}", started, request_id,
                  total=len(chunks))
        if not dropped:
            return chunks, Verdict("allow", "retriever")
        return kept, Verdict("allow", "retriever", (Finding("NEMO_INTENT_INSTRUCTION", "warn", dropped),))

    def _log(
        self, target: str, mode: str, outcome: str, started: float, request_id: str, **fields: Any
    ) -> None:
        log.info(
            "nemo_rail",
            extra={"fields": {"rail": "nemo", "target": target, "mode": mode, "outcome": outcome,
                              "latency_ms": int((time.monotonic() - started) * 1000),
                              "rid": request_id, **fields}},
        )


def build_nemo_rail(settings: Any) -> NemoRail | None:
    """설정으로 레일을 만든다. 둘 다 off 이거나 만들 수 없으면 None(= 지금과 같은 동작)."""
    query_mode = getattr(settings, "nemo_query_mode", "off")
    chunk_mode = getattr(settings, "nemo_chunk_mode", "off")
    if query_mode == "off" and chunk_mode == "off":
        return None
    from app.retrieval.embedder import get_query_embedder

    embedder = get_query_embedder()
    if embedder is None:
        log.warning("nemo_rail", extra={"fields": {"rail": "nemo", "outcome": "disabled",
                                                   "why": "no_embedder"}})
        return None
    try:
        intents = NemoIntentRail(embedder, threshold=settings.nemo_threshold)
    except Exception as e:  # noqa: BLE001 - 패키지 없음·임베더 장애 → 레일 없이 기동(fail-open)
        log.error("nemo_rail", extra={"fields": {"rail": "nemo", "outcome": "disabled",
                                                 "why": type(e).__name__}})
        return None
    return NemoRail(intents, query_mode=query_mode, chunk_mode=chunk_mode, timeout_s=settings.nemo_timeout_s)
