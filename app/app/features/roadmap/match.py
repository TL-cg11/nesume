"""C14 — 학습 갭 ↔ 콘텐츠 매칭 (순수 로직, DB·LLM 무관).

C10 갭(`LearningGap`)과 수집 콘텐츠(`LearningContent` 행을 평평하게 편 `ContentRef`)를
**역량 키 교집합**으로 붙이고, 갭마다 **가장 쓸 만한 콘텐츠**를 고른다.
매칭 규칙은 "콘텐츠의 `competency_keys`에 갭의 `key`가 들어있나" 하나뿐 — LLM이 고르지 않는다.

랭킹(한 갭 안에서): 수료증 > 평점(소스별 만점으로 0~1 정규화) > (배치 가능한) 시간 있음 > 짧은 것 > 이름순.
같은 과정의 회차(`group`)는 최상위 1개만. 학습 방법 "전체"(`mode=None`)면 모드를 섞는다(`select_for_gaps`).
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
    group: str | None = None    # 같은 과정 묶음(고용24 회차들). None이면 content_id로 따로
    match: str = "key"          # 찾은 방식: key(역량 키) / title(제목 단어) / semantic(의미 검색, AI 추천)


#: 소스별 평점 만점 — 고용24 `stdgScor`는 100점, K-MOOC는 5점. 그대로 비교하면 고용24가 늘 이긴다.
RATING_SCALE: dict[str, float] = {"work24": 100.0, "kmooc": 5.0}
MODES = ("online", "offline")


def _norm_rating(c: ContentRef) -> float:
    if not c.rating:
        return 0.0
    return min(c.rating / RATING_SCALE.get(c.source, 5.0), 1.0)


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
        -_norm_rating(c),
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
    - 같은 과정의 회차(`group`)는 최상위 1개만.
    - `mode=None`(전체): 두 모드 후보가 다 있는 갭마다 1순위 모드를 **온라인 → 오프라인 번갈아**,
      대안에는 다른 모드 최상위 1개를 반드시 넣는다. 한 모드만 있으면 그 모드로(차례는 안 넘김).
    - 갭당 상위 `per_gap`개만(대표 1 + 대안 몇 개). 매칭이 없으면 빈 튜플(사용자가 직접 채울 몫).
    """
    pool = list(contents)
    out: list[GapContent] = []
    turn = 0
    for gap in gaps:
        cands = [
            c for c in pool
            if gap.key in c.competency_keys and (mode is None or c.mode == mode)
        ]
        cands = _dedupe_groups(sorted(cands, key=_rank_key))
        if mode is None:
            cands, turned = _mix_modes(cands, MODES[turn % 2], per_gap)
            turn += turned
        out.append(GapContent(gap=gap, contents=tuple(cands[:per_gap])))
    return out


def _dedupe_groups(ranked: list[ContentRef]) -> list[ContentRef]:
    """랭킹순 목록에서 같은 `group`은 처음(최상위) 것만 남긴다."""
    seen: set[object] = set()
    out = []
    for c in ranked:
        g = c.group or c.content_id
        if g not in seen:
            seen.add(g)
            out.append(c)
    return out


def _mix_modes(ranked: list[ContentRef], first: str, per_gap: int) -> tuple[list[ContentRef], int]:
    """(1순위 = `first` 모드 최상위, 2순위 = 다른 모드 최상위, 나머지 랭킹순), 차례 사용 여부.

    두 모드가 다 있을 때만 섞고 차례(1)를 쓴다. 아니면 랭킹 그대로, 0.
    """
    best = {m: next((c for c in ranked if c.mode == m), None) for m in MODES}
    if None in best.values() or per_gap < 1:
        return ranked, 0
    other = MODES[1] if first == MODES[0] else MODES[0]
    head = [best[first], best[other]]
    return head + [c for c in ranked if c not in head], 1


def picks(sel: GapContent, *, both_modes: bool = False) -> tuple[ContentRef, ...]:
    """갭 1건에서 로드맵에 넣을 강좌. 기본은 1순위 1개.

    `both_modes`(학습 방법 "전체")면 1순위 + **다른 학습 방법의 최상위 1개**(있을 때만) — 사용자가
    두 방법을 다 보고 고른다(필요 없는 쪽은 화면에서 지움). 나머지 후보는 "이 역량 강좌 전체 보기"로.
    """
    first = sel.primary
    if first is None:
        return ()
    if not both_modes:
        return (first,)
    other = next((c for c in sel.contents[1:] if c.mode != first.mode), None)
    return (first, other) if other else (first,)


def to_learning_items(selections: Iterable[GapContent], *, both_modes: bool = False) -> list[LearningItem]:
    """갭별로 고른 강좌(`picks`)를 스케줄 입력(`LearningItem`)으로 편다(갭 순서 유지).

    한 갭에 강좌가 2개면(전체) `slot` 0·1로 구분한다 — 배치 위치를 (역량 키, 칸)으로 찾는다.
    콘텐츠가 없는 갭도 **역량만 담아** 넣는다(est_hours=0, title='') — 로드맵에 "배울 역량"으로
    보이되 시간은 안 쓴다. 사용자가 나중에 직접 콘텐츠/시간을 채운다.
    """
    items: list[LearningItem] = []
    for sel in selections:
        chosen = picks(sel, both_modes=both_modes) or (None,)
        for slot, c in enumerate(chosen):
            items.append(
                LearningItem(
                    key=sel.gap.key,
                    label=sel.gap.label,
                    importance=sel.gap.importance,
                    est_hours=c.est_hours if c else 0.0,
                    title=c.title if c else "",
                    slot=slot,
                )
            )
    return items
