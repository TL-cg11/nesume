"""B7 PII 대응표 저장소(A1 VaultStore 규약) + 사용자별 DEK 봉투 암호화.

A1의 Vault 클래스는 추합 전이므로 같은 필드를 가진 테스트용 클래스를 주입한다.
실제 A1과의 연동은 통합 작업 폴더에서 별도로 확인한다.
"""
import asyncio
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from app.db import SessionLocal
from app.features.resumes.service import ensure_user
from app.models import PiiVault, UserKey
from app.pii import envelope
from app.pii.pg_vault_store import PostgresVaultStore, cleanup_expired


@dataclass
class FakeVault:
    """A1 app.pii.vault.Vault와 같은 필드."""

    id: str
    owner_id: str
    entries: dict[str, str]
    expires_at: float | None
    format_version: int = 1


@pytest.fixture
def store():
    envelope.evict()
    return PostgresVaultStore(vault_cls=FakeVault)


@pytest.fixture
def owner():
    sub = f"pii-owner-{uuid.uuid4()}"
    with SessionLocal() as db:
        ensure_user(db, sub)
        db.commit()
    return sub


def _vault(owner, entries=None, ttl: float | None = None):
    return FakeVault(
        id=secrets.token_urlsafe(24),
        owner_id=owner,
        entries=entries or {"[[PERSON_1]]": "김철수", "[[PHONE_1]]": "010-1234-5678"},
        expires_at=None if ttl is None else time.time() + ttl,
    )


def run(coro):
    return asyncio.run(coro)


# --- 저장·복원 ---------------------------------------------------------------

def test_roundtrip_without_expiry(store, owner):
    v = _vault(owner)
    run(store.save(v))
    loaded = run(store.load(v.id))
    assert loaded == v


def test_entries_encrypted_at_rest(store, owner):
    v = _vault(owner)
    run(store.save(v))
    with SessionLocal() as db:
        raw = db.scalar(select(PiiVault.entries_enc).where(PiiVault.id == v.id))
    assert "김철수".encode() not in raw and b"010-1234-5678" not in raw


def test_one_kms_key_per_user(store, owner):
    for _ in range(3):
        run(store.save(_vault(owner)))
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).where(UserKey.user_id == owner)) == 1


def test_grade_is_sensitive(store, owner):
    v = _vault(owner)
    run(store.save(v))
    with SessionLocal() as db:
        assert db.scalar(select(PiiVault.grade).where(PiiVault.id == v.id)) == "sensitive"


def test_delete(store, owner):
    v = _vault(owner)
    run(store.save(v))
    run(store.delete(v.id))
    assert run(store.load(v.id)) is None


def test_unknown_id_returns_none(store):
    assert run(store.load("no-such-vault")) is None


# --- 만료 --------------------------------------------------------------------

def test_expired_vault_deleted_on_load(store, owner):
    v = _vault(owner, ttl=-1)
    run(store.save(v))
    assert run(store.load(v.id)) is None
    with SessionLocal() as db:
        assert db.get(PiiVault, v.id) is None


def test_ttl_vault_loads_before_expiry(store, owner):
    v = _vault(owner, ttl=1800)
    run(store.save(v))
    loaded = run(store.load(v.id))
    assert loaded.entries == v.entries and abs(loaded.expires_at - v.expires_at) < 1e-3


def test_cleanup_expired_only_and_in_batches(store, owner):
    keep_forever = _vault(owner)
    keep_live = _vault(owner, ttl=1800)
    expired = [_vault(owner, ttl=-(i + 1) * 60) for i in range(3)]
    for v in (keep_forever, keep_live, *expired):
        run(store.save(v))
    ids = [v.id for v in expired]
    with SessionLocal() as db:
        assert cleanup_expired(db, batch=2) >= 2
        cleanup_expired(db, batch=2)
        db.commit()
        assert db.scalar(select(func.count()).where(PiiVault.id.in_(ids))) == 0
        assert db.get(PiiVault, keep_forever.id) is not None
        assert db.get(PiiVault, keep_live.id) is not None


# --- 무결성·격리 -------------------------------------------------------------

def test_ciphertext_moved_to_other_vault_fails(store, owner):
    a, b = _vault(owner, {"[[PERSON_1]]": "가"}), _vault(owner, {"[[PERSON_1]]": "나"})
    run(store.save(a))
    run(store.save(b))
    with SessionLocal() as db:
        blob = db.scalar(select(PiiVault.entries_enc).where(PiiVault.id == a.id))
        db.execute(update(PiiVault).where(PiiVault.id == b.id).values(entries_enc=blob))
        db.commit()
    with pytest.raises(envelope.DecryptionFailed):
        run(store.load(b.id))


def test_ciphertext_moved_to_other_owner_fails(store, owner):
    other = f"pii-other-{uuid.uuid4()}"
    with SessionLocal() as db:
        ensure_user(db, other)
        db.commit()
    a, b = _vault(owner), _vault(other)
    run(store.save(a))
    run(store.save(b))
    with SessionLocal() as db:
        blob = db.scalar(select(PiiVault.entries_enc).where(PiiVault.id == a.id))
        db.execute(update(PiiVault).where(PiiVault.id == b.id).values(entries_enc=blob))
        db.commit()
    with pytest.raises(envelope.DecryptionFailed):
        run(store.load(b.id))


def test_same_id_from_other_owner_cannot_overwrite(store, owner):
    other = f"pii-other-{uuid.uuid4()}"
    with SessionLocal() as db:
        ensure_user(db, other)
        db.commit()
    v = _vault(owner)
    run(store.save(v))
    hijack = FakeVault(id=v.id, owner_id=other, entries={"[[PERSON_1]]": "탈취"}, expires_at=None)
    with pytest.raises(ValueError):
        run(store.save(hijack))
    assert run(store.load(v.id)).entries == v.entries


def test_destroyed_key_makes_vault_unreadable(store, owner):
    # crypto-shredding: DEK 폐기 후에는 남아 있는 암호문을 복호화할 수 없다
    v = _vault(owner)
    run(store.save(v))
    with SessionLocal() as db:
        envelope.destroy_user_key(db, owner)
        db.commit()
    envelope.evict()
    with pytest.raises(envelope.KeyUnavailable):
        run(store.load(v.id))
    with SessionLocal() as db:
        assert db.get(PiiVault, v.id) is not None  # 행은 남아도 읽을 수 없음


def test_load_does_not_create_new_key(store, owner):
    v = _vault(owner)
    run(store.save(v))
    with SessionLocal() as db:
        envelope.destroy_user_key(db, owner)
        db.commit()
    envelope.evict()
    with pytest.raises(envelope.KeyUnavailable):
        run(store.load(v.id))
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).where(UserKey.user_id == owner)) == 0


def test_dek_stored_encrypted_by_kms(store, owner):
    run(store.save(_vault(owner)))
    with SessionLocal() as db:
        row = db.get(UserKey, owner)
        dek = envelope.get_dek(db, owner)
    assert len(dek) == 32 and dek not in row.encrypted_dek


def test_cleanup_ignores_future_and_null(owner):
    with SessionLocal() as db:
        db.add(PiiVault(id=secrets.token_urlsafe(24), owner_id=owner, entries_enc=b"x", format_version=1,
                        expires_at=datetime.now(UTC) + timedelta(hours=1)))
        db.add(PiiVault(id=secrets.token_urlsafe(24), owner_id=owner, entries_enc=b"x", format_version=1,
                        expires_at=None))
        db.commit()
        before = db.scalar(select(func.count()).where(PiiVault.owner_id == owner))
        cleanup_expired(db)
        db.commit()
        assert db.scalar(select(func.count()).where(PiiVault.owner_id == owner)) == before
