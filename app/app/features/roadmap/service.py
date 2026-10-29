"""C14 — 학습 로드맵 조립 서비스 (DB 조회 + 순수 조각 조립).

입력은 **C10 학습 갭**(배워야 할 역량, 중요도순). 흐름:
  갭 키로 `LearningContent` 조회(역량 배열 교집합·활성·모드) → 갭별 콘텐츠 선택(`match`)
  → `LearningItem`으로 펴기 → 주당 시간 맞춰 주차 배치(`schedule`).

LLM은 여기 없다 — 이 배치 결과 위에 "왜 이 순서인지" 설명만 A8 경유로 붙인다(통합 단계).
로드맵 저장(행 생성)은 라우터(⑤)가 이 결과를 받아 처리한다. 이 서비스는 **계획을 계산**만 한다.
"""
from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.roadmap.match import ContentRef, GapContent, select_for_gaps, to_learning_items
from app.features.roadmap.schedule import WeeklyPlan, build_schedule
from app.features.roadmap.work24 import WORK24_SOURCE
from app.features.skill_gap.gap import LearningGap
from app.models.learning import LearningContent, LearningRoadmap, LearningRoadmapItem

#: 로드맵 항목 1행 = (항목, 딸린 콘텐츠 or None). 조회·설명 생성이 공유하는 모양.
RoadmapRow = tuple[LearningRoadmapItem, LearningContent | None]


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
        group=_group_of(row),
    )


def _group_of(row: LearningContent) -> str:
    """같은 과정 묶음 키. 고용24 external_id는 `trprId:회차:기관` → 과정(trprId)·기관 단위로 묶는다."""
    ext = row.external_id or str(row.id)
    if row.source == WORK24_SOURCE:
        parts = ext.split(":")
        ext = f"{parts[0]}:{parts[-1]}" if len(parts) == 3 else ext
    return f"{row.source}:{ext}"


def index_keys(values: dict) -> list[str]:
    """강좌 글(제목·요약·분류)에 나온 A11 사전 키. 사전 밖 말은 키가 되지 않는다."""
    from app.features.matching.vocab import matched_keys  # 지연 import(A11)

    text = " ".join(str(values.get(k) or "") for k in ("title", "summary", "classfy"))
    return sorted(matched_keys(text))


def upsert_contents(
    session: Session,
    courses: Iterable[object],
    *,
    source: str | None = None,
    mode: str = "online",
) -> dict[str, int]:
    """수집 결과를 `LearningContent`로 upsert((source, external_id) 기준). K-MOOC·고용24 공용.

    `source` 기본은 K-MOOC(기존 호출 그대로). 과정에 `mode`가 있으면(고용24: 원격=online/집체=offline)
    그 값을, 없으면 인자 `mode`를 쓴다. 과정에 없는 메타(K-MOOC의 est_hours 등)는 None.
    **`competency_keys`** = 과정이 들고 온 키(고용24 검색어) ∪ 제목·요약·분류의 A11 사전 키(`index_keys`).
    기존 행은 그 위에 **합집합**(지우지 않음 — 데모·이전 태깅 유지).
    external_id·title·url 없는 건 건너뛴다. 반환: {inserted, updated, skipped}.
    """
    if source is None:
        from app.features.roadmap.kmooc import KMOOC_SOURCE  # 지연 import(순환·망구성 분리)

        source = KMOOC_SOURCE

    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    for c in courses:
        external_id = getattr(c, "external_id", "")
        if not external_id or not getattr(c, "title", "") or not getattr(c, "url", ""):
            counts["skipped"] += 1
            continue
        values = {
            "title": c.title,
            "url": c.url,
            "provider": getattr(c, "provider", None),
            "est_hours": getattr(c, "est_hours", None),
            "weeks": getattr(c, "weeks", None),
            "summary": getattr(c, "summary", None),
            "classfy": getattr(c, "classfy", None),
            "rating": getattr(c, "rating", None),
            "certificate": getattr(c, "certificate", None),
            "mode": getattr(c, "mode", None) or mode,
            "is_active": True,
        }
        # 역량 키 = 수집기가 준 키(고용24 검색어) ∪ **A11 사전으로 제목·요약·분류를 스캔한 키**.
        # 공고 갭도 같은 사전 키라 그대로 맞는다(docs/C14.md 강좌 역량 키 색인).
        keys = list(dict.fromkeys([*(getattr(c, "competency_keys", None) or ()), *index_keys(values)]))
        existing = session.execute(
            select(LearningContent).where(
                LearningContent.source == source,
                LearningContent.external_id == external_id,
            )
        ).scalars().first()
        if existing is None:
            session.add(
                LearningContent(source=source, external_id=external_id, competency_keys=keys, **values)
            )
            counts["inserted"] += 1
        else:
            for k, v in values.items():
                setattr(existing, k, v)
            if keys:
                current = list(existing.competency_keys or [])
                existing.competency_keys = current + [k for k in keys if k not in current]
            counts["updated"] += 1
    return counts


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


#: 대체 검색에서 버리는 범용어(갭 문장 조각에 흔함)
_STOP = frozenset({
    "관련", "업무", "경험", "능력", "이해", "실무", "역량", "보유", "우대", "이상", "지식", "활용", "가능",
})
_TOKEN = re.compile(r"[0-9A-Za-z가-힣+#][0-9A-Za-z가-힣+#.\-]{1,}")


def search_token(label: str) -> str | None:
    """갭 이름에서 제목 검색에 쓸 핵심 단어 1개.

    영문·숫자 섞인 단어(IFRS17·K-ICS)를 우선, 없으면 가장 긴 단어. 범용어(`_STOP`)는 제외.
    """
    words = [w.strip(".-") for w in _TOKEN.findall(label)]
    words = [w for w in words if len(w) >= 2 and w not in _STOP]
    if not words:
        return None
    ascii_words = [w for w in words if re.search(r"[A-Za-z]", w)]
    return max(ascii_words or words, key=len)


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def fallback_contents(
    session: Session, gaps: list[LearningGap], *, mode: str | None = None, per_gap: int = 3
) -> list[ContentRef]:
    """키로 연결된 강좌가 없는 갭 → **갭 이름 핵심 단어로 강좌 제목 검색**(직무 역량 보완, 사전 밖 IFRS17 등).

    찾은 강좌에는 그 갭 키를 붙여(메모리상) `select_for_gaps`가 그대로 고르게 한다. DB의 키는 바꾸지 않는다.
    값은 바인딩 + LIKE 와일드카드 이스케이프(사용자·공고 글이 검색 패턴이 되지 않게), 갭당 `per_gap`개.
    """
    out: list[ContentRef] = []
    for g in gaps:
        token = search_token(g.label)
        if not token:
            continue
        stmt = (
            select(LearningContent)
            .where(
                LearningContent.is_active.is_(True),
                LearningContent.title.ilike(f"%{_like_escape(token)}%", escape="\\"),
            )
            .limit(per_gap)
        )
        if mode is not None:
            stmt = stmt.where(LearningContent.mode == mode)
        for row in session.execute(stmt).scalars():
            ref = _to_ref(row)
            out.append(replace(ref, competency_keys=(*ref.competency_keys, g.key)))
    return out


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
    linked = {k for c in contents for k in c.competency_keys}
    unlinked = [g for g in gaps if g.key not in linked]
    contents += fallback_contents(session, unlinked, mode=mode, per_gap=per_gap)
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
) -> list[RoadmapRow]:
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


def set_explanation(
    session: Session, *, roadmap_id: uuid.UUID, owner_id: str, text: str
) -> LearningRoadmap:
    """A8이 생성한 "왜 이 순서" 설명을 저장(재조회 시 LLM 재호출 없이 표시). 본인 것만."""
    rm = _owned(session, roadmap_id, owner_id)
    rm.explanation = text
    return rm


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
