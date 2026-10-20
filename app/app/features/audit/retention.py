"""감사 로그 90일 보관 정리 (B3, spec 10.2, part2_guide 4.25).

실행: `python -m app.features.audit.retention`
90일이 지난 행을 오래된 순으로 1회 최대 5,000행 삭제한다. 자동 실행(스케줄링)은 보류.
계정 삭제 시 user_id 익명화는 B20 담당.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AuditLog

RETENTION = timedelta(days=90)
CLEANUP_BATCH = 5000


def cleanup(db: Session, *, now: datetime | None = None, batch: int = CLEANUP_BATCH) -> int:
    """보관 기간이 지난 감사 로그를 오래된 것부터 최대 batch개 삭제하고 삭제 수를 반환한다."""
    now = now or datetime.now(UTC)
    oldest = (
        select(AuditLog.request_id)
        .where(AuditLog.timestamp < now - RETENTION)
        .order_by(AuditLog.timestamp)
        .limit(batch)
    )
    result = db.execute(delete(AuditLog).where(AuditLog.request_id.in_(oldest.scalar_subquery())))
    return result.rowcount


def main() -> int:
    with SessionLocal() as db:
        deleted = cleanup(db)
        db.commit()
    print(f"audit_logs retention cleanup: deleted={deleted}")
    return deleted


if __name__ == "__main__":
    main()
