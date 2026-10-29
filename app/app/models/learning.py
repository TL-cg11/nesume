"""C14 — 학습 콘텐츠·로드맵 (C 소유 모델). 수집기(`features/roadmap/kmooc.py`)가 콘텐츠를 적재하고,
로드맵 서비스가 사용자별 로드맵을 저장한다.

- `LearningContent`: 수집한 학습 콘텐츠(K-MOOC 등). 역량 매칭·로드맵 항목의 소스. `grade` 없음(공개 성격).
- `LearningRoadmap` / `LearningRoadmapItem`: **본인 전용**(grade=personal) 로드맵과 그 항목.
  시스템 항목은 `content_id`로 콘텐츠 참조, 사용자 추가 항목은 `content_id=NULL` + 제목·시간(+본인 링크).

※ 마이그레이션 번호·`models/__init__.py` 등록은 B가 취합(tasks.md). `job_posting_id` FK는 B가 취합 시 추가.
"""
import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import (
    CreatedAt,
    Grade,
    UpdatedAt,
    UuidPk,
    grade_check,
    grade_column,
    one_of,
    owner_fk,
)

#: 콘텐츠 출처. 온라인=kmooc(1순위)·kocw·youtube / 오프라인=work24(고용24 훈련) / user=사용자 추가.
LEARNING_SOURCES = ("kmooc", "kocw", "youtube", "work24", "user")
#: 학습 방법(모드). 도서는 범위에서 제외(2026-10-23).
LEARNING_MODES = ("online", "offline")
#: 로드맵 항목 출처(시스템 추천 / 사용자 추가)와 상태.
ITEM_ORIGINS = ("system", "user")
ITEM_STATUSES = ("planned", "in_progress", "done")
#: 시스템 항목의 강좌를 어떻게 찾았나 — 역량 키 일치 / 제목 단어 / 의미 검색(AI 추천, 관련도 낮을 수 있음).
MATCH_KINDS = ("key", "title", "semantic")


class LearningContent(Base):
    """수집한 학습 콘텐츠 1건. (source, external_id)로 유일. `competency_keys`로 역량 매칭."""

    __tablename__ = "learning_contents"
    __table_args__ = (
        one_of("source", LEARNING_SOURCES, "learning_contents_source"),
        one_of("mode", LEARNING_MODES, "learning_contents_mode"),
        Index("uq_learning_contents_source_ext", "source", "external_id", unique=True),
    )

    id: Mapped[UuidPk]
    source: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(64), index=True)  # 출처 내 강좌 ID
    mode: Mapped[str] = mapped_column(String(10), default="online", server_default="online")
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)  # 외부 링크(K-MOOC=kmooc.kr / 고용24=work24.go.kr)
    provider: Mapped[str | None] = mapped_column(Text)  # 제공 기관
    est_hours: Mapped[float | None] = mapped_column(Float)  # 주차 배치 입력(K-MOOC vod_playtime/3600)
    weeks: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)  # HTML 제거 평문(역량 매칭용)
    classfy: Mapped[str | None] = mapped_column(Text)  # 분류(매칭 보조)
    rating: Mapped[float | None] = mapped_column(Float)
    certificate: Mapped[bool | None] = mapped_column(Boolean)
    #: 역량 매칭 키(A11 정규화 키워드). 적재·색인 시 채움 → 갭 키와 교집합으로 추천.
    competency_keys: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class LearningRoadmap(Base):
    """사용자별 학습 로드맵(본인 전용, grade=personal). 공고 한 건 기준의 로드맵."""

    __tablename__ = "learning_roadmaps"
    __table_args__ = (grade_check(), one_of("mode", LEARNING_MODES, "learning_roadmaps_mode"))

    id: Mapped[UuidPk]
    owner_id: Mapped[str] = owner_fk()
    # 어떤 공고 기준 로드맵인가(C4 내부 UUID, nullable). FK는 B가 취합 시 추가(결정: 공고 사라져도 유지).
    job_posting_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    weekly_hours: Mapped[int] = mapped_column(Integer, default=5, server_default="5")  # 사용자 입력
    # 만들 때 고른 학습 방법(online/offline). NULL = 전체(온·오프 1개씩). 목록 표시용.
    mode: Mapped[str | None] = mapped_column(String(10))
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class LearningRoadmapItem(Base):
    """로드맵 항목 1건. 시스템(콘텐츠 참조) 또는 사용자 추가(제목·시간·본인 링크)."""

    __tablename__ = "learning_roadmap_items"
    __table_args__ = (
        one_of("origin", ITEM_ORIGINS, "learning_roadmap_items_origin"),
        one_of("status", ITEM_STATUSES, "learning_roadmap_items_status"),
        one_of("match_kind", MATCH_KINDS, "learning_roadmap_items_match_kind"),
    )

    id: Mapped[UuidPk]
    roadmap_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("learning_roadmaps.id", ondelete="CASCADE"), index=True
    )
    # 시스템 항목이면 콘텐츠 참조, 사용자 추가면 NULL. 콘텐츠가 비활성/삭제돼도 항목은 유지(SET NULL).
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("learning_contents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    origin: Mapped[str] = mapped_column(String(8), default="system", server_default="system")
    week: Mapped[int | None] = mapped_column(Integer)  # NULL=미배정(사용자가 주차로 이동)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 주 내 순서
    status: Mapped[str] = mapped_column(String(12), default="planned", server_default="planned")
    # 사용자 추가 항목용(시스템은 content에서 표시). URL=개인·미검증(http/https만, 공유 제외).
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    hours: Mapped[float | None] = mapped_column(Float)
    # 어느 역량(갭) 몫인가 — "이 역량 강좌 전체 보기"·교체에 쓴다. 사용자 추가 항목·0020 이전 행은 NULL.
    gap_key: Mapped[str | None] = mapped_column(Text)  # 직무 역량 키는 문장 조각일 수 있어 길이 제한 없음
    gap_label: Mapped[str | None] = mapped_column(Text)
    # 강좌를 찾은 방식(MATCH_KINDS). 강좌 없는 갭·사용자 추가는 NULL.
    match_kind: Mapped[str | None] = mapped_column(String(12))
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
