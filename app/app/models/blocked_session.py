"""D16 — 차단 세션 목록. 자동 차단(카나리·탈취 임계치)과 운영자 수동 차단이 같은 표를 쓴다.

다중 파드가 같은 목록을 봐야 하므로 DB 에 둔다(C7 `rate_limit_counters` 와 같은 이유, Redis 없음).
RAG 접근 대상이 아닌 **인프라 테이블**이라 grade/owner 없음. 행 하나 = 세션 하나의 현재 차단.
같은 세션을 다시 차단하면 행을 갱신한다(PK 가 session_id).

- `expires_at` NULL = 운영자가 풀 때까지(카나리·수동 차단 기본). 값이 있으면 그 시각까지(탈취 임계치 10분).
- `released_at` 이 차면 해제된 행. 이력으로 남겨 두고 목록 API 가 `active` 로 거른다.
- 세션 ID 는 클라이언트 헤더(X-Session-Id)라 사용자가 바꿀 수 있다 → `user_id` 를 같이 남겨 운영자가
사용자 단위로 본다.

※ `models/__init__` 등록·마이그레이션(0025)은 D 가 같이 넣었다. B 취합 규칙(tasks.md)에 따라 [B 리뷰 요청].
"""
from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt

#: 차단 사유. 자동 두 가지 + 운영자 수동.
BLOCK_REASONS = ("canary_hit", "exfil_threshold", "operator")
SYSTEM_ACTOR = "system"


class BlockedSession(Base):
    __tablename__ = "blocked_sessions"
    __table_args__ = (Index("ix_blocked_sessions_user_created", "user_id", "created_at"),)

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)  # audit_logs.session_id 와 같은 값
    user_id: Mapped[str] = mapped_column(String(128))         # Cognito sub. FK 없음(감사 로그와 같음)
    reason: Mapped[str] = mapped_column(String(50))           # BLOCK_REASONS
    rule_id: Mapped[str | None] = mapped_column(String(50))   # 걸린 규칙(LEAK_CANARY 등). 수동이면 NULL
    note: Mapped[str | None] = mapped_column(String(300))                  # 운영자 메모. 질의 원문 금지
    blocked_by: Mapped[str] = mapped_column(String(128), default=SYSTEM_ACTOR)  # "system" 또는 운영자 sub
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NULL = 해제까지
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[CreatedAt]
