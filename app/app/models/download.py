"""앱 경유 다운로드 토큰 (B6, part2_guide 4.1).

Pre-signed URL은 개별 폐기·사용자 바인딩이 불가하므로 앱이 1회용 토큰을 발급하고
검증 후 S3에서 파일을 전달한다. 토큰 원문은 저장하지 않고 SHA-256 해시만 저장한다.
만료 24시간 후 정리 배치(core.storage.cleanup)가 삭제한다.
"""
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, UuidPk, owner_fk


class DownloadToken(Base):
    __tablename__ = "download_tokens"
    __table_args__ = (
        # 정리 배치: 오래된 만료 토큰부터 삭제
        Index("ix_download_tokens_expires_at", "expires_at"),
        # 재발급 시 같은 파일의 미사용 토큰 폐기
        Index(
            "ix_download_tokens_active_object", "owner_id", "object_key",
            postgresql_where=text("used_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    id: Mapped[UuidPk]
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    owner_id: Mapped[str] = owner_fk()
    object_key: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[CreatedAt]

