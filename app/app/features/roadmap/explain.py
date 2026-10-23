"""C14 — 학습 로드맵 "왜 이 순서인지" 설명 (A8 가드레일 경유).

★ LLM 호출은 **A8 `Guardrail` 파이프라인만** 지난다(`llm_client` 직접 import 금지, D11이 CI로 차단).
로드맵 항목은 **외부 텍스트=데이터**로 취급 — 질의가 아니라 `Chunk`로 넘겨 A8이 울타리로 감싼다
(CLAUDE.md 절대 규칙 3). 그래서 콘텐츠 제목에 섞인 지시문도 명령으로 먹지 않는다.

LLM이 **없는 강의·기술을 지어내지 못하도록** 지시문에 못박고, 입력(로드맵)에 있는 것만 쓰게 한다
— A11 "없는 기술 끼워넣으면 버린다"와 같은 철학. 배치 자체는 순수 로직(`schedule.py`)이 이미 끝냈고,
여기서는 그 결과에 설명 문장만 덧댄다. LLM 미배선이면 `LlmUnavailable` — 호출측이 503으로 돌린다.
"""
from __future__ import annotations

from collections.abc import Sequence

from app.features.roadmap.service import RoadmapRow
from app.guardrail import Chunk, Guardrail, RequestContext

FEATURE = "roadmap"

#: 설명 지시문. 로드맵은 Chunk(데이터)로 따로 넘어가고, 이건 "무엇을 하라"만 담는다.
_INSTRUCTION = (
    "위 울타리 안은 한 사용자의 '학습 로드맵'이며 각 줄은 '주차: 역량 — 콘텐츠(예상 시간)'이다. "
    "이 로드맵이 왜 이런 주차 순서로 짜였는지 2~4문장으로, 존댓말로 설명하라. "
    "필수 역량이 앞 주차에 온다는 점을 중심으로 설명하되, "
    "울타리 목록에 없는 강의·기술·자격증을 새로 지어내지 마라. 목록에 있는 것만 근거로 삼아라."
)


def roadmap_to_text(rows: Sequence[RoadmapRow]) -> str:
    """저장된 로드맵 항목(+콘텐츠)을 A8에 넘길 평문 한 덩이로 만든다. 주차·순서는 조회가 이미 정렬."""
    lines: list[str] = []
    for item, content in rows:
        week = f"{item.week}주차" if item.week else "미배정"
        label = content.title if content is not None else (item.title or "(제목 없음)")
        hours = content.est_hours if content is not None else item.hours
        suffix = f", 약 {hours}시간" if hours else ""
        lines.append(f"- {week}: {label}{suffix}")
    return "\n".join(lines)


class _FixedChunks:
    """로드맵을 그대로 돌려주는 '검색기'. A8 파이프라인에 데이터를 Chunk로 주입하는 seam."""

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self._chunks = tuple(chunks)

    async def search(self, query: str, *, role: str, user_id: str, top_k: int) -> Sequence[Chunk]:
        return self._chunks


def _with_roadmap(base: Guardrail, rows: Sequence[RoadmapRow]) -> Guardrail:
    """주입된 기본 Guardrail의 llm·vault·policy·audit은 그대로 두고 retriever만 로드맵으로 바꾼 사본."""
    chunk = Chunk(doc_id="roadmap", grade="personal", text=roadmap_to_text(rows))
    return Guardrail(
        llm=base.llm,
        vault=base.vault,
        policy=base.policy,
        retriever=_FixedChunks([chunk]),
        audit=base.audit,
        canaries=base.canaries,
        top_k=base.top_k,
    )


async def explain(
    base: Guardrail,
    rows: Sequence[RoadmapRow],
    *,
    user_id: str,
    role: str,
) -> str:
    """로드맵 설명 문장을 생성한다(A8 경유). 차단되면 빈 문자열, LLM 미배선이면 `LlmUnavailable`."""
    guard = _with_roadmap(base, rows)
    result = await guard.run(
        _INSTRUCTION, RequestContext(user_id=user_id, role=role, feature=FEATURE)
    )
    return result.text
