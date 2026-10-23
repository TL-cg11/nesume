"""멘토 공유 (spec 3.7). 공유 이력의 원본.

resumes.shared_with(B2)와 벡터 메타데이터(C3)는 B10 공유 API에서 이 테이블과 동기화한다.
"""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, UuidPk, owner_fk


class Share(Base):
    __tablename__ = "shares"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint("shared_with <> owner_id", name="not_self"),
        # 멘토별 유효 공유 조회(공유 대상 + 미취소 + 만료 전)용 부분 인덱스
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
    # 공유 시점의 문항별 버전 고정(B10, part2_guide 4.40). 이후 수정본은 멘토에게 보이지 않는다.
    # FK 없음(applications.version_ids와 같은 방식). 버전은 수정·개별 삭제 불가라 참조가 깨지지 않는다
    version_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list, server_default="{}")
    created_at: Mapped[CreatedAt]
