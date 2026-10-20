"""임베딩 테이블 (C 소유 모델). C3 파이프라인이 적재하고 C6 검색이 조회한다.

공개 인덱스(공고)와 개인 인덱스(자소서·경험)를 분리한다(C9). 필터 버그가 나도
공개 인덱스 검색에서 개인 문서가 안 나오게 하는 2차 방어선.

사전 필터(spec 8.2)를 벡터 테이블만 보고 할 수 있도록, 등급·소유자·공유·삭제 메타를
벡터 행에 **복제(denormalize)**한다. C2 build_where / C6 search 가 이 컬럼들에 바로 WHERE를 건다.
벡터 차원 1024 = bge-m3. 유사도는 코사인(bge-m3는 정규화 임베딩) → vector_cosine_ops.

※ 마이그레이션 번호 지정·`models/__init__.py` 등록은 B가 취합(tasks.md). 공고 FK는 C4
  job_postings 모델 생성 시 추가(현재는 source_id로 느슨히 참조).
"""
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import (
    CreatedAt,
    DeletedAt,
    Grade,
    UpdatedAt,
    UuidPk,
    grade_check,
    grade_column,
    owner_fk,
)

#: bge-m3 임베딩 차원 (docs/C_임베딩모델_제안.md)
EMBED_DIM = 1024


def _hnsw_index(name: str) -> Index:
    """HNSW + 코사인. 필터와 함께 쓸 땐 세션에서 hnsw.iterative_scan 설정(C1 결론)."""
    return Index(
        name,
        "embedding",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


class JobPostingEmbedding(Base):
    """공개 인덱스 — 공고 청크. 항상 grade=public, owner/shared 없음."""

    __tablename__ = "job_posting_embeddings"
    __table_args__ = (grade_check(), _hnsw_index("ix_jpe_hnsw"))

    id: Mapped[UuidPk]
    # C4 job_postings 생성 시 FK로 전환. 지금은 느슨히 참조.
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    content: Mapped[str] = mapped_column(Text)  # A1 mask 적용 텍스트(복원 불필요)
    grade: Mapped[str] = grade_column(Grade.PUBLIC)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class UserProfileEmbedding(Base):
    """개인 인덱스 — 자소서·경험 청크. owner_id 필수, 자소서는 shared_with(JSONB)."""

    __tablename__ = "user_profile_embeddings"
    __table_args__ = (
        grade_check(),
        Index("ix_upe_owner", "owner_id"),
        _hnsw_index("ix_upe_hnsw"),
    )

    id: Mapped[UuidPk]
    owner_id: Mapped[str] = owner_fk()
    source_type: Mapped[str] = mapped_column(String(20))  # "resume" / "experience"
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    content: Mapped[str] = mapped_column(Text)  # A1 처리(토큰화 or 마스킹, docs/C3.md 미결정) 텍스트
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    # 자소서만: 멘토 공유 [{"user_id","expires_at"}] — B resumes.shared_with 복제(B10 동기화)
    shared_with: Mapped[list[dict]] = mapped_column(JSONB, default=list, server_default="[]")
    # 원본(resume/experience) 소프트 삭제 복제 → C6가 deleted_at IS NULL 필터(B 요청)
    deleted_at: Mapped[DeletedAt]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
