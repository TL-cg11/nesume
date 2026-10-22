"""A1 VaultStore의 Postgres + KMS 구현 (B7, part2_guide 4.26).

A1(`app/app/pii/vault.py`)의 VaultStore 규약을 따른다.
    async save(vault) / async load(vault_id) -> Vault | None / async delete(vault_id)

- entries(토큰 → 원문)는 소유자 DEK로 AES-GCM 암호화, AAD = "vault_id|owner_id"
- expires_at이 None이면 만료 없음(저장용 대응표). 문서 삭제 시 호출자가 delete한다.
- load 시 만료된 대응표는 실제로 삭제하고 None을 반환한다(A1 규약).
  다시 열리지 않는 만료 대응표는 cleanup_expired 배치가 지운다(1회 최대 1,000행, 자동 실행 보류).
- PostgresVaultStore: 연산마다 자체 트랜잭션(LLM 경로용). SessionVaultStore: 요청 세션 공유(B4·B5 저장용).
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


def save_in(db: Session, vault) -> None:
    """주어진 세션에 대응표를 저장한다(flush만, 커밋은 호출자)."""
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
        raise ValueError("vault id already belongs to another owner")


def load_in(db: Session, vault_id: str, vault_cls=None):
    """주어진 세션에서 대응표를 읽는다. 없거나 만료면 None(만료분은 삭제, flush만)."""
    row = db.scalar(select(PiiVault).where(PiiVault.id == vault_id))
    if row is None:
        return None
    if row.expires_at is not None and row.expires_at <= datetime.now(UTC):
        db.delete(row)
        db.flush()
        return None
    dek = envelope.get_dek(db, row.owner_id)  # 폐기됐으면 KeyUnavailable
    entries = json.loads(envelope.decrypt(dek, row.entries_enc, _aad(row.id, row.owner_id)))
    cls = vault_cls or _default_vault_cls()
    return cls(
        id=row.id,
        owner_id=row.owner_id,
        entries=entries,
        expires_at=None if row.expires_at is None else row.expires_at.timestamp(),
        format_version=row.format_version,
    )


def delete_in(db: Session, vault_id: str) -> None:
    db.execute(delete(PiiVault).where(PiiVault.id == vault_id))


class PostgresVaultStore:
    """연산마다 자체 세션·트랜잭션으로 커밋한다. LLM 경로(A8) 등 독립 호출용."""

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
            try:
                save_in(db, vault)
            except ValueError:
                db.rollback()
                raise
            db.commit()

    def _load(self, vault_id: str):
        with self._session_factory() as db:
            vault = load_in(db, vault_id, self._vault_cls)
            db.commit()  # 만료분 삭제 반영
            return vault

    def _delete(self, vault_id: str) -> None:
        with self._session_factory() as db:
            delete_in(db, vault_id)
            db.commit()


class SessionVaultStore:
    """요청 세션을 그대로 쓰는 저장소(B4·B5 저장 경로, part2_guide 4.33).

    대응표가 자소서 버전·경험과 **같은 트랜잭션**에 저장되어, 본문 저장이 실패하면 대응표도 남지 않는다.
    개인정보가 없어 entries가 비면 저장하지 않는다(호출자는 vault_id를 비워 둔다).
    같은 스레드에서 순차 실행되므로 세션을 공유해도 안전하다.
    """

    def __init__(self, db: Session, vault_cls=None):
        self._db = db
        self._vault_cls = vault_cls

    async def save(self, vault) -> None:
        if not vault.entries:
            return
        save_in(self._db, vault)
        self._db.flush()

    async def load(self, vault_id: str):
        return load_in(self._db, vault_id, self._vault_cls)

    async def delete(self, vault_id: str) -> None:
        delete_in(self._db, vault_id)
        self._db.flush()


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
