"""앱 경유 1회용 다운로드 토큰 (B6, part2_guide 4.1, 4.23).

- 유효 10분(spec 3.2), 1회용, 발급자 본인만 사용.
- 재발급 시 같은 사용자·같은 객체의 미사용 토큰을 폐기한다(spec 3.2 "재발급 시 이전 URL 폐기").
- 토큰 원문은 반환만 하고 저장하지 않는다(SHA-256 해시 저장).
- 만료 24시간이 지난 토큰은 정리 배치가 1회 최대 1,000행씩 삭제한다.
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import DownloadToken

TOKEN_TTL = timedelta(minutes=10)
RETENTION_AFTER_EXPIRY = timedelta(hours=24)
CLEANUP_BATCH = 1000


@dataclass(frozen=True)
class Redeemed:
    object_key: str
    filename: str
    content_type: str


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(
    db: Session, owner_id: str, object_key: str, filename: str, content_type: str,
    *, now: datetime | None = None,
) -> tuple[str, datetime]:
    """토큰을 발급하고 (토큰 원문, 만료 시각)을 반환한다. 호출자는 소유권을 먼저 확인해야 한다."""
    now = now or datetime.now(UTC)
    db.execute(
        update(DownloadToken)
        .where(
            DownloadToken.owner_id == owner_id,
            DownloadToken.object_key == object_key,
            DownloadToken.used_at.is_(None),
            DownloadToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    token = secrets.token_urlsafe(32)
    expires_at = now + TOKEN_TTL
    db.add(DownloadToken(
        token_hash=_hash(token), owner_id=owner_id, object_key=object_key,
        filename=filename, content_type=content_type, expires_at=expires_at,
    ))
    db.flush()
    return token, expires_at


def redeem(db: Session, requester_id: str, token: str, *, now: datetime | None = None) -> Redeemed | None:
    """유효하면 사용 처리하고 대상 정보를 반환한다. 무효·만료·사용됨·타인 토큰은 None.

    조건부 UPDATE 한 문장으로 처리해 동시 요청에서도 한 번만 성공한다.
    타인이 시도한 경우 토큰을 소모하지 않는다.
    """
    now = now or datetime.now(UTC)
    row = db.execute(
        update(DownloadToken)
        .where(
            DownloadToken.token_hash == _hash(token),
            DownloadToken.owner_id == requester_id,
            DownloadToken.used_at.is_(None),
            DownloadToken.revoked_at.is_(None),
            DownloadToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(DownloadToken.object_key, DownloadToken.filename, DownloadToken.content_type)
    ).one_or_none()
    return Redeemed(*row) if row else None


def cleanup(db: Session, *, now: datetime | None = None, batch: int = CLEANUP_BATCH) -> int:
    """만료 후 24시간이 지난 토큰을 오래된 것부터 최대 batch개 삭제하고 삭제 수를 반환한다."""
    now = now or datetime.now(UTC)
    oldest = (
        select(DownloadToken.id)
        .where(DownloadToken.expires_at < now - RETENTION_AFTER_EXPIRY)
        .order_by(DownloadToken.expires_at)
        .limit(batch)
    )
    result = db.execute(delete(DownloadToken).where(DownloadToken.id.in_(oldest.scalar_subquery())))
    return result.rowcount
