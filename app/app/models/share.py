"""멘토 공유 (spec 3.7). shared_with·expires_at(B2)의 원본.

벡터 DB가 같은 PostgreSQL(pgvector)이므로 검색 필터(C6)는 이 테이블을 직접 조인하는 것을 권장한다.
벡터 메타데이터로 복제하면 취소·만료가 즉시 반영되지 않을 수 있다(spec 3.7 "즉시 접근 불가").
"""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, UuidPk, owner_fk


class Share(Base):
    __tablename__ = "shares"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint("shared_with <> owner_id", name="not_self"),
        # 검색 필터(C6)·권한 판정이 "공유 대상 + 미취소 + 만료 전"을 조인으로 확인할 때 사용
        Index(
            "ix_shares_active_lookup", "shared_with", "resume_id", "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[UuidPk]
    resume_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = owner_fk()
    shared_with: Mapped[str] = mapped_column(
        String(128), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 기본 7일·최대 30일 규칙은 서비스 계층(B10)에서 검증한다
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[CreatedAt]
