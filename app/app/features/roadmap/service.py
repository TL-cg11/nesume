"""C14 — 학습 로드맵 조립 서비스 (DB 조회 + 순수 조각 조립).

입력은 **C10 학습 갭**(배워야 할 역량, 중요도순). 흐름:
  갭 키로 `LearningContent` 조회(역량 배열 교집합·활성·모드) → 갭별 콘텐츠 선택(`match`)
  → `LearningItem`으로 펴기 → 주당 시간 맞춰 주차 배치(`schedule`).

LLM은 여기 없다 — 이 배치 결과 위에 "왜 이 순서인지" 설명만 A8 경유로 붙인다(통합 단계).
로드맵 저장(행 생성)은 라우터(⑤)가 이 결과를 받아 처리한다. 이 서비스는 **계획을 계산**만 한다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.roadmap.match import ContentRef, GapContent, select_for_gaps, to_learning_items
from app.features.roadmap.schedule import WeeklyPlan, build_schedule
from app.features.skill_gap.gap import LearningGap
from app.models.learning import LearningContent, LearningRoadmap, LearningRoadmapItem


@dataclass(frozen=True)
class RoadmapPlan:
    """계산된 로드맵 1건(저장 전). 라우터가 이걸 받아 행으로 저장하거나 그대로 응답한다."""

    weeks: list[WeeklyPlan]            # 주차 배치(스케줄)
    selections: list[GapContent]       # 갭별 선택 콘텐츠(대표+대안, 표시·저장용)
    uncovered: list[LearningGap]       # 매칭 콘텐츠가 없는 갭(사용자가 직접 채울 몫)


def _to_ref(row: LearningContent) -> ContentRef:
    """`LearningContent` 행 → 순수 매칭 입력(`ContentRef`)."""
    return ContentRef(
        content_id=row.id,
        source=row.source,
        title=row.title,
        url=row.url,
        mode=row.mode,
        competency_keys=tuple(row.competency_keys or ()),
        est_hours=row.est_hours or 0.0,
        weeks=row.weeks,
        rating=row.rating,
        certificate=row.certificate,
        provider=row.provider,
    )


def fetch_contents(
    session: Session,
    keys: list[str],
    *,
    mode: str | None = None,
) -> list[ContentRef]:
    """갭 키들에 매칭될 수 있는 활성 콘텐츠를 조회한다(사전 필터).

    `competency_keys && keys`(배열 교집합, PostgreSQL overlap)로 DB에서 1차로 거른다 —
    키 없으면 빈 리스트(쿼리 생략). `mode`가 있으면 그 모드만.
    """
    if not keys:
        return []
    stmt = select(LearningContent).where(
        LearningContent.is_active.is_(True),
        LearningContent.competency_keys.overlap(keys),
    )
    if mode is not None:
        stmt = stmt.where(LearningContent.mode == mode)
    return [_to_ref(r) for r in session.execute(stmt).scalars().all()]


def build_roadmap(
    session: Session,
    gaps: list[LearningGap],
    *,
    weekly_hours: int = 5,
    mode: str | None = None,
    max_weeks: int | None = None,
    per_gap: int = 3,
) -> RoadmapPlan:
    """학습 갭 → 콘텐츠 매칭 → 주차 배치까지 한 번에 계산한다.

    갭이 없으면 빈 계획. 콘텐츠가 전혀 없어도 갭은 역량 항목으로 배치에 포함된다(시간 0).
    """
    keys = [g.key for g in gaps]
    contents = fetch_contents(session, keys, mode=mode)
    selections = select_for_gaps(gaps, contents, mode=mode, per_gap=per_gap)
    items = to_learning_items(selections)
    weeks = build_schedule(items, weekly_hours=weekly_hours, max_weeks=max_weeks)
    uncovered = [s.gap for s in selections if s.primary is None]
    return RoadmapPlan(weeks=weeks, selections=selections, uncovered=uncovered)


# --- 저장·조회·수정 (본인 전용, DB) ------------------------------------------------

class RoadmapNotFound(Exception):
    """해당 사용자의 로드맵/항목이 아니거나 존재하지 않음(남의 것은 404)."""


def _owned(session: Session, roadmap_id: uuid.UUID, owner_id: str) -> LearningRoadmap:
    rm = session.get(LearningRoadmap, roadmap_id)
    if rm is None or rm.owner_id != owner_id:
        raise RoadmapNotFound(str(roadmap_id))
    return rm


def _placement(weeks: list[WeeklyPlan]) -> dict[str, tuple[int, int]]:
    """스케줄에서 역량 키별 **최초 등장 주차·그 주 내 순서**를 뽑는다(긴 과정은 여러 주 → 첫 주)."""
    out: dict[str, tuple[int, int]] = {}
    for wp in weeks:
        pos = 0
        for s in wp.items:
            if s.item.key not in out:
                out[s.item.key] = (wp.week, pos)
                pos += 1
    return out


def save_roadmap(
    session: Session,
    *,
    owner_id: str,
    job_posting_id: uuid.UUID | None,
    weekly_hours: int,
    plan: RoadmapPlan,
) -> LearningRoadmap:
    """계산된 계획을 본인 로드맵으로 저장한다(시스템 항목). grade=personal·owner는 모델/여기서 고정.

    시스템 항목은 `content_id`로 콘텐츠 참조(제목·링크는 읽을 때 조인). 매칭 콘텐츠가 없는 갭은
    `content_id=NULL`에 **역량명을 title로** 남겨 "배울 역량(콘텐츠 없음)"으로 보이게 한다.
    """
    roadmap = LearningRoadmap(
        owner_id=owner_id,
        job_posting_id=job_posting_id,
        weekly_hours=weekly_hours,
    )
    session.add(roadmap)
    session.flush()  # roadmap.id 확보

    place = _placement(plan.weeks)
    for idx, sel in enumerate(plan.selections):
        week, pos = place.get(sel.gap.key, (None, idx))
        content = sel.primary
        session.add(
            LearningRoadmapItem(
                roadmap_id=roadmap.id,
                content_id=content.content_id if content else None,
                origin="system",
                week=week,
                position=pos,
                status="planned",
                title=None if content else sel.gap.label,  # 콘텐츠 없는 갭은 역량명 표시
            )
        )
    return roadmap


def list_roadmaps(session: Session, *, owner_id: str) -> list[LearningRoadmap]:
    """본인 로드맵 목록(최근 수정순)."""
    return list(
        session.execute(
            select(LearningRoadmap)
            .where(LearningRoadmap.owner_id == owner_id)
            .order_by(LearningRoadmap.updated_at.desc())
        ).scalars().all()
    )


def get_roadmap(session: Session, *, roadmap_id: uuid.UUID, owner_id: str) -> LearningRoadmap:
    """본인 로드맵 1건(없거나 남의 것이면 RoadmapNotFound)."""
    return _owned(session, roadmap_id, owner_id)


def get_items(
    session: Session, *, roadmap_id: uuid.UUID, owner_id: str
) -> list[tuple[LearningRoadmapItem, LearningContent | None]]:
    """로드맵 항목 + 딸린 콘텐츠(시스템 항목만, 사용자 항목은 None). 주차·순서순.

    콘텐츠가 비활성/삭제돼도(`content_id` SET NULL) 항목은 남는다(outer join).
    """
    _owned(session, roadmap_id, owner_id)  # 소유 확인(남의 로드맵 항목 열람 차단)
    return list(
        session.execute(
            select(LearningRoadmapItem, LearningContent)
            .outerjoin(LearningContent, LearningContent.id == LearningRoadmapItem.content_id)
            .where(LearningRoadmapItem.roadmap_id == roadmap_id)
            .order_by(LearningRoadmapItem.week.nulls_last(), LearningRoadmapItem.position)
        ).all()
    )


def update_weekly_hours(
    session: Session, *, roadmap_id: uuid.UUID, owner_id: str, weekly_hours: int
) -> LearningRoadmap:
    """주당 가용 시간만 수정(재배치는 호출측이 재계산해 항목 주차를 바꾼다)."""
    rm = _owned(session, roadmap_id, owner_id)
    rm.weekly_hours = weekly_hours
    return rm


def delete_roadmap(session: Session, *, roadmap_id: uuid.UUID, owner_id: str) -> None:
    """로드맵 삭제(항목 CASCADE). 본인 것만."""
    session.delete(_owned(session, roadmap_id, owner_id))


def add_user_item(
    session: Session,
    *,
    roadmap_id: uuid.UUID,
    owner_id: str,
    title: str,
    url: str | None = None,
    hours: float | None = None,
    week: int | None = None,
) -> LearningRoadmapItem:
    """사용자가 직접 추가하는 항목(origin=user). URL은 **개인·미검증**(스키마가 http/https만 통과)."""
    _owned(session, roadmap_id, owner_id)
    item = LearningRoadmapItem(
        roadmap_id=roadmap_id,
        content_id=None,
        origin="user",
        week=week,
        position=0,
        status="planned",
        title=title,
        url=url,
        hours=hours,
    )
    session.add(item)
    return item


def _owned_item(
    session: Session, roadmap_id: uuid.UUID, item_id: uuid.UUID, owner_id: str
) -> LearningRoadmapItem:
    _owned(session, roadmap_id, owner_id)  # 로드맵 소유 먼저
    item = session.get(LearningRoadmapItem, item_id)
    if item is None or item.roadmap_id != roadmap_id:
        raise RoadmapNotFound(str(item_id))
    return item


def update_item(
    session: Session,
    *,
    roadmap_id: uuid.UUID,
    item_id: uuid.UUID,
    owner_id: str,
    status: str | None = None,
    week: int | None = None,
    position: int | None = None,
) -> LearningRoadmapItem:
    """항목 상태(완료 체크)·주차 이동·순서 수정. None인 필드는 안 바꾼다."""
    item = _owned_item(session, roadmap_id, item_id, owner_id)
    if status is not None:
        item.status = status
    if week is not None:
        item.week = week
    if position is not None:
        item.position = position
    return item


def delete_item(
    session: Session, *, roadmap_id: uuid.UUID, item_id: uuid.UUID, owner_id: str
) -> None:
    """항목 1건 삭제. 본인 로드맵의 항목만."""
    session.delete(_owned_item(session, roadmap_id, item_id, owner_id))
