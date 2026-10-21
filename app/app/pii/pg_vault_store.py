"""A1 VaultStore의 Postgres + KMS 구현 (B7, part2_guide 4.26).

A1(`app/app/pii/vault.py`)의 VaultStore 규약을 따른다.
    async save(vault) / async load(vault_id) -> Vault | None / async delete(vault_id)

- entries(토큰 → 원문)는 소유자 DEK로 AES-GCM 암호화, AAD = "vault_id|owner_id"
- expires_at이 None이면 만료 없음(저장용 대응표). 문서 삭제 시 호출자가 delete한다.
- load 시 만료된 대응표는 실제로 삭제하고 None을 반환한다(A1 규약).
  다시 열리지 않는 만료 대응표는 cleanup_expired 배치가 지운다(1회 최대 1,000행, 자동 실행 보류).
- 각 연산은 자체 트랜잭션으로 커밋한다. DB·KMS 호출은 스레드에서 실행해 이벤트 루프를 막지 않는다.
- 소유자 확인은 A1 detokenize가 한다(vault.owner_id 비교).
"""
import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import PiiVault
from app.pii import envelope

CLEANUP_BATCH = 1000


def _aad(vault_id: str, owner_id: str) -> bytes:
    return f"{vault_id}|{owner_id}".encode()


def _to_dt(epoch: float | None) -> datetime | None:
    return None if epoch is None else datetime.fromtimestamp(epoch, UTC)


def _default_vault_cls():
    # A1이 같은 패키지에 Vault를 제공한다. 추합 전 브랜치에서는 vault_cls를 주입해 사용한다.
    from app.pii.vault import Vault

    return Vault


class PostgresVaultStore:
    def __init__(self, session_factory: Callable[[], Session] = SessionLocal, vault_cls=None):
        self._session_factory = session_factory
        self._vault_cls = vault_cls

    # --- A1 VaultStore 규약 ---------------------------------------------------

    async def save(self, vault) -> None:
        await asyncio.to_thread(self._save, vault)

    async def load(self, vault_id: str):
        return await asyncio.to_thread(self._load, vault_id)

    async def delete(self, vault_id: str) -> None:
        await asyncio.to_thread(self._delete, vault_id)

    # --- 동기 구현 ------------------------------------------------------------

    def _save(self, vault) -> None:
        with self._session_factory() as db:
            dek = envelope.get_or_create_dek(db, vault.owner_id)
            payload = json.dumps(vault.entries, ensure_ascii=False).encode()
            values = dict(
                id=vault.id,
                owner_id=vault.owner_id,
                entries_enc=envelope.encrypt(dek, payload, _aad(vault.id, vault.owner_id)),
                format_version=vault.format_version,
                expires_at=_to_dt(vault.expires_at),
            )
            written = db.scalar(
                insert(PiiVault).values(**values).on_conflict_do_update(
                    index_elements=[PiiVault.id],
                    set_={k: values[k] for k in ("entries_enc", "format_version", "expires_at")},
                    # 다른 소유자의 같은 id 덮어쓰기 금지
                    where=PiiVault.owner_id == vault.owner_id,
                ).returning(PiiVault.id)
            )
            # rowcount는 드라이버가 -1을 줄 수 있어 RETURNING으로 반영 여부를 판정한다
            if written is None:
                db.rollback()
                raise ValueError("vault id already belongs to another owner")
            db.commit()

    def _load(self, vault_id: str):
        with self._session_factory() as db:
            row = db.scalar(select(PiiVault).where(PiiVault.id == vault_id))
            if row is None:
                return None
            if row.expires_at is not None and row.expires_at <= datetime.now(UTC):
                db.delete(row)
                db.commit()
                return None
            dek = envelope.get_dek(db, row.owner_id)  # 폐기됐으면 KeyUnavailable
            entries = json.loads(envelope.decrypt(dek, row.entries_enc, _aad(row.id, row.owner_id)))
            cls = self._vault_cls or _default_vault_cls()
            return cls(
                id=row.id,
                owner_id=row.owner_id,
                entries=entries,
                expires_at=None if row.expires_at is None else row.expires_at.timestamp(),
                format_version=row.format_version,
            )

    def _delete(self, vault_id: str) -> None:
        with self._session_factory() as db:
            db.execute(delete(PiiVault).where(PiiVault.id == vault_id))
            db.commit()


def cleanup_expired(db: Session, *, now: datetime | None = None, batch: int = CLEANUP_BATCH) -> int:
    """만료된 대응표를 만료 시각이 오래된 순으로 최대 batch개 삭제한다. 만료 없음(NULL)은 대상 아님."""
    now = now or datetime.now(UTC)
    oldest = (
        select(PiiVault.id)
        .where(PiiVault.expires_at.is_not(None), PiiVault.expires_at <= now)
        .order_by(PiiVault.expires_at)
        .limit(batch)
    )
    return db.execute(delete(PiiVault).where(PiiVault.id.in_(oldest.scalar_subquery()))).rowcount


def main() -> int:
    """실행: `python -m app.pii.pg_vault_store` (자동 실행 보류)."""
    with SessionLocal() as db:
        deleted = cleanup_expired(db)
        db.commit()
    print(f"pii_vaults expired cleanup: deleted={deleted}")
    return deleted


if __name__ == "__main__":
    main()
