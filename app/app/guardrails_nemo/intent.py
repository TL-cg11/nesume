"""NeMo Guardrails 의도 판정(C16). 순수 판정만 — 파이프라인 연결·감사 로그 기록은 하지 않는다.

- 임베딩: 우리 `Embedder`(bge-m3, TEI)를 NeMo 공급자 `nesume_bge_m3` 로 꽂는다. 기본 FastEmbed 를 쓰지 않는다.
  같은 문장은 다시 임베딩하지 않는다(캐시) — 점수 계산·조각 묶음 임베딩이 임베더를 더 부르지 않게.
- 의도 → 판정: 권한 외 `flag`, 탈취 `block`, 문서 속 지시문 `drop`(그 조각 제외), 그 밖 `allow`.
- 실패는 `NemoError(reason)` 로 올린다. 호출부(rail.py)가 fail-open 으로 다룬다.
"""

from __future__ import annotations

import asyncio
import math
import re
import threading
from collections import OrderedDict
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
#: rails.co 의 `define user …` 이름 → 우리 의도(점수 계산용)
_COLANG_INTENT: dict[str, Intent] = {
    "ask other users data": "authz",
    "extract system": "exfil",
    "embedded instruction": "instruction",
    "normal request": "normal",
}
_CACHE_MAX = 4096


class NemoError(RuntimeError):
    """판정 실패. ``reason`` 은 로그용 짧은 코드(질의 내용 없음)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# NeMo 가 공급자 클래스를 이름으로 만들기 때문에 인스턴스를 넘길 자리가 없다. 만들기 직전에 여기 둔다
_current_embedder: Embedder | None = None
_cache: OrderedDict[str, list[float]] = OrderedDict()
_cache_lock = threading.Lock()
#: 마지막 임베딩 실패 종류. NeMo 가 예외를 삼키고 "internal error" 문구만 돌려주므로 원인을 여기서 읽는다
_last_embed_error: str | None = None


def _embed_cached(texts: list[str]) -> list[list[float]]:
    global _last_embed_error
    if _current_embedder is None:
        raise NemoError("no_embedder")
    with _cache_lock:
        missing = list(dict.fromkeys(t for t in texts if t not in _cache))
    if missing:
        try:
            vecs = _current_embedder.embed(missing)
        except Exception as e:
            _last_embed_error = type(e).__name__
            raise
        with _cache_lock:
            for t, v in zip(missing, vecs, strict=True):
                _cache[t] = v
                _cache.move_to_end(t)
            while len(_cache) > _CACHE_MAX:
                _cache.popitem(last=False)
    with _cache_lock:
        return [_cache[t] for t in texts]


@dataclass(frozen=True)
class NemoResult:
    intent: Intent
    #: 가장 가까운 예시 문장과의 점수(NeMo 와 같은 척도). 기준값 조정 근거로 로그에 남긴다
    score: float | None = None
    #: 그 예시 문장이 속한 의도(판정과 다를 수 있다 — 기준값 아래면 판정은 normal)
    nearest: Intent | None = None

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

        def encode(self, documents: list[str]) -> list[list[float]]:
            return _embed_cached(list(documents))

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


def colang_examples(config_dir: Path = CONFIG_DIR) -> list[tuple[Intent, str]]:
    """rails.co 의 (의도, 예시 문장). 점수 계산과 시험이 같이 쓴다."""
    out: list[tuple[Intent, str]] = []
    current: Intent | None = None
    for line in (config_dir / "rails.co").read_text(encoding="utf-8").splitlines():
        m = re.match(r"define user (.+)$", line.strip())
        if m:
            current = _COLANG_INTENT.get(m.group(1).strip())
            continue
        if line.strip().startswith("define "):
            current = None
            continue
        q = re.match(r'^\s+"(.+)"\s*$', line)
        if q and current is not None:
            out.append((current, q.group(1)))
    return out


def _nemo_score(a: list[float], b: list[float]) -> float:
    cos = sum(x * y for x, y in zip(a, b, strict=True))
    return 1.0 - math.sqrt(max(0.0, 2.0 - 2.0 * cos)) / 2.0  # NeMo basic.py 와 같은 척도(정규화 벡터)


class NemoIntentRail:
    """설정(config/) + 임베더로 만든 의도 판정기. 예시 색인은 첫 호출 때 만든다."""

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
        self._examples = colang_examples(config_dir)
        self._rails = LLMRails(config)
        # NeMo 는 예시 색인을 첫 호출 때 만든다. 첫 요청들이 동시에 오면 색인 전에 검색해 내부 오류가 난다
        # (11-03 로컬 재현) → 첫 호출 하나만 색인을 만들게 하고 나머지는 기다린다
        self._ready = False
        self._lock = asyncio.Lock()

    async def warmup(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if not self._ready:
                await self._generate("안녕하세요")
                self._ready = True

    async def prefetch(self, texts: list[str]) -> None:
        """여러 문장을 임베딩 한 번으로 캐시에 넣는다(검색 조각 — 하나씩 부르면 임베더가 밀린다)."""
        await asyncio.to_thread(_embed_cached, list(texts))

    async def acheck(self, text: str) -> NemoResult:
        await self.warmup()
        intent = parse_intent(await self._generate(text))
        try:
            nearest, score = await asyncio.to_thread(self._best, text)  # 캐시에 있어 임베더를 부르지 않는다
        except Exception:  # noqa: BLE001 - 점수는 기록용. 판정은 이미 났다
            nearest, score = None, None
        return NemoResult(intent, score, nearest)

    def _best(self, text: str) -> tuple[Intent, float]:
        vecs = _embed_cached([text] + [t for _, t in self._examples])
        q, rest = vecs[0], vecs[1:]
        i, score = max(enumerate(_nemo_score(q, v) for v in rest), key=lambda p: p[1])
        return self._examples[i][0], round(score, 3)

    async def _generate(self, text: str) -> str:
        global _last_embed_error
        _last_embed_error = None
        res = await self._rails.generate_async(messages=[{"role": "user", "content": text}])
        content = str(res.get("content", ""))
        if not content.startswith(_PREFIX):
            # 우리 봇 문구가 아니면 NeMo 내부 오류("I'm sorry, an internal error…")다. 정상으로 읽지 않는다
            why = f"embedder_{_last_embed_error}" if _last_embed_error else "nemo_internal"
            raise NemoError(why)
        return content

    def check_many(self, texts: list[str]) -> list[NemoResult]:
        async def run() -> list[NemoResult]:
            return [await self.acheck(t) for t in texts]

        return asyncio.run(run())
