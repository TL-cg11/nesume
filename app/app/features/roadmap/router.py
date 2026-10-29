"""C14 — 학습 로드맵 API. 본인 전용 생성·조회·수정·완료체크·항목 추가.

흐름: 갭(요청) → 콘텐츠 매칭·주차 배치(`service.build_roadmap`) → 저장(`save_roadmap`) → 조회.
- **본인 전용**: 모든 작업 owner=토큰 `sub`, 남의 것은 404(`RoadmapNotFound`). grade=personal 고정.
- **LLM 호출 없음**: 순서·주차 배치는 규칙(`schedule.py`).
  "왜 이 순서인지" LLM 설명은 2026-10-29 제거(docs/C14.md).
- 출력/이미지 저장은 **프런트**(조회 결과를 렌더·캡처) — 서버 엔드포인트 아님.
main.py 등록은 D에 PR로 요청(features/__init__.py 규칙).
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.db import get_db
from app.features.roadmap import service
from app.features.roadmap.schemas import (
    CandidateOut,
    CandidatePick,
    CandidatesOut,
    ItemUpdate,
    LearningMode,
    RoadmapCreate,
    RoadmapItemOut,
    RoadmapOut,
    RoadmapUpdate,
    UserItemCreate,
)
from app.models.learning import LearningContent, LearningRoadmap, LearningRoadmapItem
from app.postings.read import get_posting_fields, get_posting_link
from app.retrieval.embedder import get_embedder

router = APIRouter(prefix="/roadmaps", tags=["roadmaps"])
Db = Annotated[Session, Depends(get_db)]

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def _item_out(item: LearningRoadmapItem, content: LearningContent | None) -> RoadmapItemOut:
    """항목 + 콘텐츠 → 응답. 시스템 항목은 콘텐츠에서, 사용자/콘텐츠없음 항목은 inline에서 값."""
    if content is not None:  # 시스템 항목(콘텐츠 참조)
        return RoadmapItemOut(
            id=item.id,
            origin=item.origin,
            status=item.status,
            week=item.week,
            position=item.position,
            unverified=False,
            title=content.title,
            url=content.url,
            hours=content.est_hours,
            source=content.source,
            provider=content.provider,
            certificate=content.certificate,
            content_id=content.id,
            mode=content.mode,
            gap_key=item.gap_key,
            gap_label=item.gap_label,
            match_kind=item.match_kind,
        )
    # 사용자 추가 항목 또는 매칭 콘텐츠 없는 시스템 갭(inline title)
    return RoadmapItemOut(
        id=item.id,
        origin=item.origin,
        status=item.status,
        week=item.week,
        position=item.position,
        unverified=item.origin == "user" and bool(item.url),  # 미검증 외부 링크 표시
        title=item.title,
        url=item.url,
        hours=item.hours,
        gap_key=item.gap_key,
        gap_label=item.gap_label,
    )


def _roadmap_out(db: Session, roadmap: LearningRoadmap, owner_id: str) -> RoadmapOut:
    out = RoadmapOut.model_validate(roadmap)
    if roadmap.job_posting_id:  # 공고는 C4 창구로만(권한 규칙 그대로 — 못 보면 None)
        fields = get_posting_fields(db, roadmap.job_posting_id, user_id=owner_id)
        link = get_posting_link(db, roadmap.job_posting_id, user_id=owner_id) if fields else None
        out.posting_title = fields["title"] if fields else None
        out.company_name = link["company_name"] if link else None
    out.items = [
        _item_out(item, content)
        for item, content in service.get_items(db, roadmap_id=roadmap.id, owner_id=owner_id)
    ]
    return out


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RoadmapOut)
def create_roadmap(payload: RoadmapCreate, user: AuthenticatedUser, db: Db):
    """갭 → 콘텐츠 매칭·주차 배치 → 저장. 콘텐츠 없는 갭도 '배울 역량'으로 남는다."""
    plan = service.build_roadmap(
        db,
        [g.to_gap() for g in payload.gaps],
        weekly_hours=payload.weekly_hours,
        mode=payload.mode.value if payload.mode else None,
        max_weeks=payload.max_weeks,
        embedder=get_embedder(),
    )
    roadmap = service.save_roadmap(
        db,
        owner_id=user.sub,
        job_posting_id=payload.job_posting_id,
        weekly_hours=payload.weekly_hours,
        plan=plan,
        mode=payload.mode.value if payload.mode else None,
    )
    db.flush()
    return _roadmap_out(db, roadmap, user.sub)


@router.get("", response_model=list[RoadmapOut])
def list_roadmaps(user: AuthenticatedUser, db: Db):
    return [_roadmap_out(db, rm, user.sub) for rm in service.list_roadmaps(db, owner_id=user.sub)]


@router.get("/{roadmap_id}", response_model=RoadmapOut)
def get_roadmap(roadmap_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    try:
        rm = service.get_roadmap(db, roadmap_id=roadmap_id, owner_id=user.sub)
    except service.RoadmapNotFound:
        raise _NOT_FOUND from None
    return _roadmap_out(db, rm, user.sub)


@router.patch("/{roadmap_id}", response_model=RoadmapOut)
def update_roadmap(roadmap_id: uuid.UUID, payload: RoadmapUpdate, user: AuthenticatedUser, db: Db):
    try:
        rm = service.update_weekly_hours(
            db, roadmap_id=roadmap_id, owner_id=user.sub, weekly_hours=payload.weekly_hours
        )
    except service.RoadmapNotFound:
        raise _NOT_FOUND from None
    db.flush()
    return _roadmap_out(db, rm, user.sub)


@router.delete("/{roadmap_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_roadmap(roadmap_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    try:
        service.delete_roadmap(db, roadmap_id=roadmap_id, owner_id=user.sub)
    except service.RoadmapNotFound:
        raise _NOT_FOUND from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{roadmap_id}/items", status_code=status.HTTP_201_CREATED, response_model=RoadmapItemOut)
def add_item(roadmap_id: uuid.UUID, payload: UserItemCreate, user: AuthenticatedUser, db: Db):
    """사용자 추가 항목(origin=user). URL은 스키마에서 http/https만 통과(개인·미검증)."""
    try:
        item = service.add_user_item(
            db,
            roadmap_id=roadmap_id,
            owner_id=user.sub,
            title=payload.title,
            url=payload.url,
            hours=payload.hours,
            week=payload.week,
        )
    except service.RoadmapNotFound:
        raise _NOT_FOUND from None
    db.flush()
    return _item_out(item, None)


@router.patch("/{roadmap_id}/items/{item_id}", response_model=RoadmapItemOut)
def update_item(
    roadmap_id: uuid.UUID, item_id: uuid.UUID, payload: ItemUpdate, user: AuthenticatedUser, db: Db
):
    """완료 체크(status)·주차 이동(week)·순서(position). 응답은 콘텐츠 재조인해 표시값 포함."""
    try:
        service.update_item(
            db,
            roadmap_id=roadmap_id,
            item_id=item_id,
            owner_id=user.sub,
            status=payload.status.value if payload.status else None,
            week=payload.week,
            position=payload.position,
        )
    except service.RoadmapNotFound:
        raise _NOT_FOUND from None
    db.flush()
    for item, content in service.get_items(db, roadmap_id=roadmap_id, owner_id=user.sub):
        if item.id == item_id:
            return _item_out(item, content)
    raise _NOT_FOUND


@router.delete("/{roadmap_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(roadmap_id: uuid.UUID, item_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    try:
        service.delete_item(db, roadmap_id=roadmap_id, item_id=item_id, owner_id=user.sub)
    except service.RoadmapNotFound:
        raise _NOT_FOUND from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


#: "전체 보기" 페이지 크기 상한(한 번에 너무 많이 내려주지 않게).
MAX_PAGE_SIZE = 50


@router.get("/{roadmap_id}/items/{item_id}/candidates", response_model=CandidatesOut)
def list_candidates(
    roadmap_id: uuid.UUID,
    item_id: uuid.UUID,
    user: AuthenticatedUser,
    db: Db,
    mode: LearningMode | None = None,
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
):
    """이 항목 역량의 강좌 **전부**(키 일치·제목 단어·의미 검색), 평점순·페이지. 본인 로드맵만."""
    try:
        total, refs, in_roadmap = service.item_candidates(
            db,
            roadmap_id=roadmap_id,
            item_id=item_id,
            owner_id=user.sub,
            mode=mode.value if mode else None,
            page=page,
            size=size,
            embedder=get_embedder(),
        )
    except service.RoadmapNotFound:
        raise _NOT_FOUND from None
    except service.NoGapInfo:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "역량 정보가 없는 항목입니다. 로드맵을 다시 생성해 주세요."
        ) from None
    return CandidatesOut(
        total=total,
        page=page,
        size=size,
        items=[
            CandidateOut(
                content_id=r.content_id,
                title=r.title,
                url=r.url,
                source=r.source,
                mode=r.mode,
                provider=r.provider,
                hours=r.est_hours or None,
                weeks=r.weeks,
                rating=r.rating,
                certificate=r.certificate,
                match_kind=r.match,
                in_roadmap=r.content_id in in_roadmap,
            )
            for r in refs
        ],
    )


@router.post("/{roadmap_id}/items/{item_id}/candidates", response_model=RoadmapItemOut)
def pick_candidate(
    roadmap_id: uuid.UUID, item_id: uuid.UUID, payload: CandidatePick, user: AuthenticatedUser, db: Db
):
    """목록에서 고른 강좌로 **교체**(`replace=true`) 또는 같은 역량·주차에 **추가**. 활성 강좌만."""
    fn = service.replace_with_candidate if payload.replace else service.add_candidate
    try:
        item = fn(
            db, roadmap_id=roadmap_id, item_id=item_id, owner_id=user.sub, content_id=payload.content_id
        )
    except service.RoadmapNotFound:
        raise _NOT_FOUND from None
    except service.NoGapInfo:
        raise HTTPException(status.HTTP_409_CONFLICT, "역량 정보가 없는 항목입니다.") from None
    except service.ContentUnavailable:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "강좌를 찾을 수 없습니다") from None
    db.flush()
    return _item_out(item, db.get(LearningContent, item.content_id))
