"""C7 — 레이트리밋 카운터 (고정 창). 운영용 PostgresStore가 쓰는 공유 상태.

다중 파드(HPA)가 같은 카운터를 봐야 하므로 DB에 둔다(파드 메모리 불가, docs/C7.md).
RAG 접근 대상이 아닌 **인프라 테이블**이라 grade/owner 없음. `key`는 "req:<uid>"·"tok:<uid>"·
"exfil:<session>" 같은 축별 키. `window_start`는 epoch 초(창 시작), 창 만료 시 upsert가 리셋한다.

※ `models/__init__` 등록·마이그레이션은 B 취합(tasks.md). [B 리뷰 요청]
"""
from sqlalchemy import BigInteger, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import UpdatedAt


class RateLimitCounter(Base):
    """키별 고정 창 카운터 1행. (window_start, count)로 "현재 창에 얼마나 쌓였나"를 센다."""

    __tablename__ = "rate_limit_counters"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)  # 축:식별자 (req:/tok:/exfil:)
    window_start: Mapped[float] = mapped_column(Float)               # epoch 초, 창 시작 시각
    count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    updated_at: Mapped[UpdatedAt]
