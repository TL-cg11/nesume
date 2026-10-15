"""멘토 공유 (spec 3.7). 공유 정보의 원본이며 벡터 메타데이터에는 C3가 반영한다."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, UuidPk, owner_fk


class Share(Base):
    __tablename__ = "shares"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint("shared_with <> owner_id", name="not_self"),
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
