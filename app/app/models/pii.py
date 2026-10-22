"""B7 PII 대응표 저장 (spec 8.3, tasks B7, part2_guide 4.26).

- user_keys: 사용자별 데이터 키(DEK). KMS로 암호화된 상태로만 저장한다(봉투 암호화).
  계정 삭제 시 이 행을 지우면 해당 사용자의 대응표는 백업에 남아 있어도 복호화할 수 없다.
- pii_vaults: A1 대응표(토큰 → 원문). 원문 묶음(entries)은 사용자 DEK로 AES-GCM 암호화.
  expires_at이 NULL이면 만료 없음(저장용), 값이 있으면 LLM 경로용(기본 30분).
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, Grade, grade_check, grade_column, owner_fk


class UserKey(Base):
    __tablename__ = "user_keys"

    user_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    encrypted_dek: Mapped[bytes] = mapped_column(LargeBinary)
    kms_key_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[CreatedAt]


class PiiVault(Base):
    __tablename__ = "pii_vaults"
    __table_args__ = (
        grade_check(),
        # 만료 대응표 정리 배치: 만료된 것 중 오래된 순
        Index("ix_pii_vaults_expires_at", "expires_at", postgresql_where=text("expires_at IS NOT NULL")),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # A1 vault id(token_urlsafe)
    owner_id: Mapped[str] = owner_fk()
    # nonce(12바이트) + AES-GCM 암호문. 평문은 entries JSON
    entries_enc: Mapped[bytes] = mapped_column(LargeBinary)
    format_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # PII 원문은 민감 등급(tasks B8)
    grade: Mapped[str] = grade_column(Grade.SENSITIVE)
    created_at: Mapped[CreatedAt]
