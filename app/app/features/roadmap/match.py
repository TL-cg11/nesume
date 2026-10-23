"""C14 — 학습 갭 ↔ 콘텐츠 매칭 (순수 로직, DB·LLM 무관).

C10 갭(`LearningGap`)과 수집 콘텐츠(`LearningContent` 행을 평평하게 편 `ContentRef`)를
**역량 키 교집합**으로 붙이고, 갭마다 **가장 쓸 만한 콘텐츠**를 고른다.
매칭 규칙은 "콘텐츠의 `competency_keys`에 갭의 `key`가 들어있나" 하나뿐 — LLM이 고르지 않는다.

랭킹(한 갭 안에서): 수료증 > 평점 > (배치 가능한) 시간 있음 > 짧은 것 > 이름순.
콘텐츠 행을 직접 import하지 않고 `ContentRef`로 받는다(덕타이핑 — DB 없이 테스트, 모델 변경에 둔감).
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from app.features.roadmap.schedule import LearningItem
from app.features.skill_gap.gap import LearningGap


@dataclass(frozen=True)
class ContentRef:
    """매칭·배치에 필요한 콘텐츠 최소 모양(서비스가 `LearningContent` 행에서 만든다).

    `est_hours`는 없으면 0.0(배치는 0을 "시간 미상"으로 취급). `competency_keys`는 역량 매칭 키.
    """

    content_id: uuid.UUID
    source: str
    title: str
    url: str
    mode: str
    competency_keys: tuple[str, ...]
    est_hours: float = 0.0
    weeks: int | None = None
    rating: float | None = None
    certificate: bool | None = None
    provider: str | None = None


@dataclass(frozen=True)
class GapContent:
    """갭 1건 + 그 갭에 매칭된 콘텐츠(랭킹순, 없으면 빈 튜플)."""

    gap: LearningGap
    contents: tuple[ContentRef, ...]

    @property
    def primary(self) -> ContentRef | None:
        """스케줄·대표 표시에 쓰는 1순위 콘텐츠(없으면 None)."""
        return self.contents[0] if self.contents else None


def _rank_key(c: ContentRef) -> tuple:
    """한 갭 안에서 콘텐츠 우선순위. 수료증 → 평점↓ → 시간 있음 → 짧은 것 → 이름."""
    return (
        0 if c.certificate else 1,
        -(c.rating or 0.0),
        0 if c.est_hours > 0 else 1,
        c.est_hours if c.est_hours > 0 else float("inf"),
        c.title.casefold(),
    )


def select_for_gaps(
    gaps: Iterable[LearningGap],
    contents: Iterable[ContentRef],
    *,
    mode: str | None = None,
    per_gap: int = 3,
) -> list[GapContent]:
    """갭마다 매칭 콘텐츠를 골라 랭킹순으로 담는다(갭 입력 순서 = 중요도순 유지).

    - 매칭: 콘텐츠 `competency_keys`에 갭 `key`가 있으면 후보.
    - `mode`를 주면 그 모드(online/offline)만 남긴다(서비스가 DB에서 이미 걸러도 여기서 한 번 더).
    - 갭당 상위 `per_gap`개만(대표 1 + 대안 몇 개). 매칭이 없으면 빈 튜플(사용자가 직접 채울 몫).
    """
    pool = list(contents)
    out: list[GapContent] = []
    for gap in gaps:
        cands = [
            c for c in pool
            if gap.key in c.competency_keys and (mode is None or c.mode == mode)
        ]
        cands.sort(key=_rank_key)
        out.append(GapContent(gap=gap, contents=tuple(cands[:per_gap])))
    return out


def to_learning_items(selections: Iterable[GapContent]) -> list[LearningItem]:
    """갭별 1순위 콘텐츠를 스케줄 입력(`LearningItem`)으로 편다(갭 순서 유지).

    콘텐츠가 없는 갭도 **역량만 담아** 넣는다(est_hours=0, title='') — 로드맵에 "배울 역량"으로
    보이되 시간은 안 쓴다. 사용자가 나중에 직접 콘텐츠/시간을 채운다.
    """
    items: list[LearningItem] = []
    for sel in selections:
        c = sel.primary
        items.append(
            LearningItem(
                key=sel.gap.key,
                label=sel.gap.label,
                importance=sel.gap.importance,
                est_hours=c.est_hours if c else 0.0,
                title=c.title if c else "",
            )
        )
    return items
