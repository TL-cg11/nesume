from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, DeletedAt


class User(Base):
    """서비스 사용자. 역할은 저장하지 않고 매 요청 토큰(cognito:groups)에서 읽는다(spec 7.4)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # Cognito sub
    # 계정 삭제 시 감사 로그 user_id를 치환할 익명화 토큰(spec 10.2). 삭제 처리 시 발급.
    anon_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[CreatedAt]
    deleted_at: Mapped[DeletedAt]
