"""모델 공통 요소: 기본 컬럼 타입, 타임스탬프, 값 목록 CHECK 제약."""
import uuid
from datetime import datetime
from typing import Annotated

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

# Cognito sub(UUID 문자열). 시스템 계정 등 비UUID 식별자 가능성을 고려해 문자열로 둔다.
UserId = Annotated[str, mapped_column(String(128))]

UuidPk = Annotated[
    uuid.UUID,
    mapped_column(Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")),
]
CreatedAt = Annotated[
    datetime, mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
]
UpdatedAt = Annotated[
    datetime,
    mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False),
]
DeletedAt = Annotated[datetime | None, mapped_column(DateTime(timezone=True), nullable=True)]


def owner_fk() -> Mapped[str]:
    """소유자 FK. 사용자 물리 삭제 시 소유 문서도 함께 삭제한다(B20)."""
    return mapped_column(
        String(128), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )


def one_of(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    """PG ENUM 대신 CHECK 제약으로 값 목록을 고정한다(값 추가 시 마이그레이션이 단순)."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)
