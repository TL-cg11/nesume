"""C14 — 학습 로드맵 API. 본인 전용 생성·조회·수정·완료체크·항목 추가.

흐름: 갭(요청) → 콘텐츠 매칭·주차 배치(`service.build_roadmap`) → 저장(`save_roadmap`) → 조회.
- **본인 전용**: 모든 작업 owner=토큰 `sub`, 남의 것은 404(`RoadmapNotFound`). grade=personal 고정.
- **LLM 직접 호출 없음**: 배치까지 순수/DB. "왜 이 순서인지" 설명은 통합 단계에서 A8 경유로 덧댄다.
- 출력/이미지 저장은 **프런트**(조회 결과를 렌더·캡처) — 서버 엔드포인트 아님.
main.py 등록은 D에 PR로 요청(features/__init__.py 규칙).
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.db import get_db
from app.features.roadmap import service
from app.features.roadmap.explain import explain
from app.features.roadmap.schemas import (
    ItemUpdate,
    RoadmapCreate,
    RoadmapItemOut,
    RoadmapOut,
    RoadmapUpdate,
    UserItemCreate,
)
from app.guardrail import Guardrail, LlmUnavailable
from app.guardrail.fastapi import get_guardrail as shared_guardrail
from app.models.learning import LearningContent, LearningRoadmap, LearningRoadmapItem

router = APIRouter(prefix="/roadmaps", tags=["roadmaps"])
Db = Annotated[Session, Depends(get_db)]


def get_guardrail() -> Guardrail:
    """앱 공유 가드레일(A8) — `app.guardrail.fastapi.get_guardrail`에 위임.

    전에는 여기서 빈 `Guardrail()`을 만들어 **감사 로그(B11 DbAuditSink)가 빠진 LLM 경로**였고,
    D가 공유 가드레일에 LLM 제공자를 주입해도 C14 설명엔 안 들어왔다. 공유 인스턴스를 쓰면
    감사·대화 이력·제공자 주입이 다른 기능과 같아진다. 테스트는 이 의존성을 덮어써서 갈아끼운다.
    """
    return shared_guardrail()


GuardrailDep = Annotated[Guardrail, Depends(get_guardrail)]

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
    )


def _roadmap_out(db: Session, roadmap: LearningRoadmap, owner_id: str) -> RoadmapOut:
    out = RoadmapOut.model_validate(roadmap)
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
    )
    roadmap = service.save_roadmap(
        db,
        owner_id=user.sub,
        job_posting_id=payload.job_posting_id,
        weekly_hours=payload.weekly_hours,
        plan=plan,
    )
    db.flush()
    return _roadmap_out(db, roadmap, user.sub)


@router.post("/{roadmap_id}/explain", response_model=RoadmapOut)
async def explain_roadmap(roadmap_id: uuid.UUID, user: AuthenticatedUser, db: Db, guard: GuardrailDep):
    """"왜 이 순서인지" 설명을 A8 경유로 생성·저장. 로드맵은 데이터로 펜싱(LLM이 못 지어냄).

    LLM 프로바이더 미배선(D 통합 전)이면 503 — 로드맵 자체는 설명 없이도 동작한다.
    """
    try:
        service.get_roadmap(db, roadmap_id=roadmap_id, owner_id=user.sub)  # 소유 확인
    except service.RoadmapNotFound:
        raise _NOT_FOUND from None
    rows = service.get_items(db, roadmap_id=roadmap_id, owner_id=user.sub)
    try:
        text = await explain(guard, rows, user_id=user.sub, role=user.role.value)
    except LlmUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "LLM 미배선") from None
    rm = service.set_explanation(db, roadmap_id=roadmap_id, owner_id=user.sub, text=text)
    db.flush()
    return _roadmap_out(db, rm, user.sub)


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
