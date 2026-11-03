"""C16 NeMo 레일 — 가드레일 파이프라인의 `InputRail` 포트 구현(pipeline.py).

- 모드: ``shadow``(판정을 바꾸지 않고 로그만 — 파이프라인이 기다리지 않는다) / ``enforce``(판정에 합친다)
  / ``off``. 질의와 검색 조각을 따로 정한다(`NEMO_QUERY_MODE`, `NEMO_CHUNK_MODE`). 기본은 둘 다 off.
- 시간: enforce 는 ``timeout_s``(3초)까지만 기다리고, 넘으면 통과(`NEMO_TIMEOUT`)시키되 검사는 뒤에서
  ``shadow_timeout_s``(30초)까지 계속 돌려 **늦은 판정**(late)을 기록한다 — 느려서 놓친 것이 무엇인지 남긴다.
  shadow 는 처음부터 ``shadow_timeout_s``. 뒤에서 도는 검사는 ``max_background`` 개까지(넘으면 건너뛰고 기록).
- 올리기만 한다: 탈취·지시문 → block, 권한 외 → allow + 표식. A3 가 막은 것을 풀지 않는다(merge 가 보장).
- 오류는 fail-open — allow + `NEMO_ERROR`(info). 1차 방어(A3)는 그대로 있다.
- 로그: ``nesume.guardrail.rail`` 에 ``nemo_rail`` 한 줄. 질의 원문 없음 — 의도·점수·원인 코드·지연·늦음 여부.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from app.guardrail.pipeline import Chunk
from app.guardrail.schema import Finding, Verdict
from app.guardrails_nemo.intent import NemoError, NemoIntentRail, NemoResult

log = logging.getLogger("nesume.guardrail.rail")

Mode = Literal["off", "shadow", "enforce"]
MODES: tuple[Mode, ...] = ("off", "shadow", "enforce")
RULE_ERROR = "NEMO_ERROR"
RULE_TIMEOUT = "NEMO_TIMEOUT"

_ERROR = object()  # 판정 실패 표시(로그는 이미 남김)


def _reason(e: BaseException) -> str:
    if isinstance(e, NemoError):
        return e.reason
    if isinstance(e, asyncio.TimeoutError | TimeoutError):
        return "timeout"
    return type(e).__name__


class NemoRail:
    def __init__(
        self,
        intents: Any,
        *,
        query_mode: Mode,
        chunk_mode: Mode,
        timeout_s: float = 3.0,
        shadow_timeout_s: float = 30.0,
        max_background: int = 8,
    ):
        if query_mode not in MODES or chunk_mode not in MODES:
            raise ValueError(f"NeMo 모드는 {MODES} 중 하나여야 한다")
        self._intents = intents  # NemoIntentRail(또는 같은 acheck 를 가진 가짜)
        self.query_mode: Mode = query_mode
        self.chunk_mode: Mode = chunk_mode
        self._timeout_s = timeout_s
        self._shadow_timeout_s = max(shadow_timeout_s, timeout_s)
        self._max_background = max_background
        self._background = 0
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ 질의

    async def check_query(self, text: str, request_id: str = "") -> Verdict:
        res = await self._judge("query", self.query_mode, lambda: self._intents.acheck(text), request_id)
        if res is None or res is _ERROR or self.query_mode != "enforce":
            return self._fallback(res, "classifier")
        assert isinstance(res, NemoResult)
        if res.intent in ("exfil", "instruction"):
            return Verdict("block", "classifier", (Finding(res.rule_id or RULE_ERROR, "critical"),),
                           query_type="exfiltration")
        if res.intent == "authz":
            return Verdict("allow", "classifier", (Finding(res.rule_id or RULE_ERROR, "warn"),))
        return Verdict("allow", "classifier")

    # ------------------------------------------------------------------ 검색 조각

    async def check_chunks(
        self, chunks: Sequence[Chunk], request_id: str = ""
    ) -> tuple[Sequence[Chunk], Verdict]:
        """지시문 의도로 판정된 조각을 뺀다. 판정은 allow + 표식(뺀 개수) — 나머지로 계속 답한다."""
        texts = [c.text for c in chunks]

        async def job() -> list[NemoResult]:
            prefetch = getattr(self._intents, "prefetch", None)
            if prefetch is not None:
                await prefetch(texts)  # 임베딩 한 번으로 묶는다
            return list(await asyncio.gather(*(self._intents.acheck(t) for t in texts)))

        res = await self._judge("chunks", self.chunk_mode, job, request_id)
        if res is None or res is _ERROR or self.chunk_mode != "enforce":
            return chunks, self._fallback(res, "retriever")
        kept = [c for c, r in zip(chunks, res, strict=True) if r.intent != "instruction"]
        dropped = len(chunks) - len(kept)
        if not dropped:
            return chunks, Verdict("allow", "retriever")
        return kept, Verdict("allow", "retriever", (Finding("NEMO_INTENT_INSTRUCTION", "warn", dropped),))

    # ------------------------------------------------------------------ 시간·로그

    async def _judge(self, target: str, mode: str, job: Callable[[], Awaitable[Any]], rid: str) -> Any:
        """판정을 돌린다. 돌려주는 값: 결과 / ``_ERROR``(실패) / ``None``(enforce 시간 초과 — 뒤에서 계속)."""
        started = time.monotonic()
        if mode != "enforce":  # shadow: 파이프라인이 이미 띄워 둔 작업이다. 상한만 지킨다
            if self._background >= self._max_background:
                self._log(target, mode, "skipped", started, rid, why="background_full")
                return _ERROR
            self._background += 1
            try:
                return await self._run(target, mode, job, rid, started)
            finally:
                self._background -= 1

        task = asyncio.ensure_future(self._run(target, mode, job, rid, started))
        done, _ = await asyncio.wait({task}, timeout=self._timeout_s)
        if done:
            return task.result()
        # 3초 넘음 → 통과시키고 검사는 뒤에서 마저 돌린다(늦은 판정 기록). 상한이 차면 접는다
        if self._background >= self._max_background:
            task.cancel()
            self._log(target, mode, "skipped", started, rid, why="background_full")
        else:
            self._background += 1
            self._tasks.add(task)
            task.add_done_callback(self._release)
        return None

    def _release(self, task: asyncio.Task) -> None:
        self._background -= 1
        self._tasks.discard(task)

    async def _run(self, target: str, mode: str, job: Callable[[], Awaitable[Any]], rid: str, started: float):
        try:
            res = await asyncio.wait_for(job(), self._shadow_timeout_s)
        except Exception as e:  # noqa: BLE001 - fail-open. 원인 코드만 남긴다
            self._log(target, mode, "error", started, rid, why=_reason(e))
            return _ERROR
        late = mode == "enforce" and time.monotonic() - started > self._timeout_s
        if isinstance(res, NemoResult):
            self._log(target, mode, res.intent, started, rid, score=res.score, nearest=res.nearest, late=late)
        else:
            flagged = [r for r in res if r.intent == "instruction"]
            top = max((r.score for r in res if r.score is not None), default=None)
            self._log(target, mode, f"dropped={len(flagged)}", started, rid, total=len(res),
                      top_score=top, late=late)
        return res

    def _fallback(self, res: Any, stage: str) -> Verdict:
        if res is None:  # enforce 시간 초과 — 통과, 판정은 뒤에서 기록
            return Verdict("allow", stage, (Finding(RULE_TIMEOUT, "info"),))
        if res is _ERROR:
            return Verdict("allow", stage, (Finding(RULE_ERROR, "info"),))
        return Verdict("allow", stage)  # shadow: 판정은 로그에만

    def _log(
        self, target: str, mode: str, outcome: str, started: float, request_id: str, **fields: Any
    ) -> None:
        log.info(
            "nemo_rail",
            extra={"fields": {"rail": "nemo", "target": target, "mode": mode, "outcome": outcome,
                              "latency_ms": int((time.monotonic() - started) * 1000),
                              "rid": request_id, **{k: v for k, v in fields.items() if v is not None}}},
        )


def build_nemo_rail(settings: Any) -> NemoRail | None:
    """설정으로 레일을 만든다. 둘 다 off 이거나 만들 수 없으면 None(= 지금과 같은 동작)."""
    query_mode = getattr(settings, "nemo_query_mode", "off")
    chunk_mode = getattr(settings, "nemo_chunk_mode", "off")
    if query_mode == "off" and chunk_mode == "off":
        return None
    from app.retrieval.embedder import get_embedder

    # 배치 정책(60초·재시도) 임베더를 쓴다. 첫 호출 때 예시 63문장을 색인하는데, dev 임베더(CPU)는 32문장에
    # 약 5초라 요청 경로용(5초·재시도 없음)으로는 색인이 실패했다(11-03 dev). 질의 1건 지연은 rail 의
    # timeout_s 가 따로 막는다(질의 1건 실측 0.1초)
    embedder = get_embedder()
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
    return NemoRail(
        intents, query_mode=query_mode, chunk_mode=chunk_mode, timeout_s=settings.nemo_timeout_s,
        shadow_timeout_s=getattr(settings, "nemo_shadow_timeout_s", 30.0),
        max_background=getattr(settings, "nemo_max_background", 8),
    )
