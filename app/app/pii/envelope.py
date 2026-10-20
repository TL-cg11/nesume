"""사용자별 데이터 키(DEK) 봉투 암호화 (B7, part2_guide 5.3).

- DEK는 KMS GenerateDataKey로 발급하고 KMS로 암호화된 상태(user_keys)로만 저장한다.
  EncryptionContext에 user_id를 넣어 다른 사용자 행으로 옮긴 암호화 키는 풀리지 않는다.
- 데이터는 앱에서 AES-256-GCM으로 암호화한다. AAD로 소속(대응표 ID·소유자)을 묶어
  암호문을 다른 행으로 옮기면 복호화가 실패한다.
- 복호화된 DEK는 프로세스 메모리에 짧게(5분) 캐시해 KMS 호출을 줄인다.
- 계정 삭제 시 destroy_user_key로 DEK를 폐기하면 그 사용자의 암호문은 복호화할 수 없다.

소유: B7(B팀). 경로는 part2_guide 4.26 결정에 따라 A 소유 `app/app/pii/` 하위(추합 시 A 리뷰).
이 패키지의 `__init__.py`는 A1이 소유하므로 B는 만들지 않는다.
"""
import os
import time
from threading import Lock

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import aws
from app.config import get_settings
from app.models import UserKey

NONCE_SIZE = 12
DEK_CACHE_TTL_SECONDS = 300
DEK_CACHE_MAX = 1024

_cache: dict[str, tuple[bytes, float]] = {}
_cache_lock = Lock()


class KeyUnavailable(Exception):
    """사용자 DEK가 없음(폐기됨). 해당 사용자의 암호문은 복호화할 수 없다."""


class DecryptionFailed(Exception):
    """암호문이 변조됐거나 다른 행·다른 키의 것이다."""


def _context(user_id: str) -> dict[str, str]:
    return {"user_id": user_id}


def _cache_get(user_id: str) -> bytes | None:
    with _cache_lock:
        hit = _cache.get(user_id)
        if hit and hit[1] > time.monotonic():
            return hit[0]
        _cache.pop(user_id, None)
        return None


def _cache_put(user_id: str, dek: bytes) -> None:
    with _cache_lock:
        if len(_cache) >= DEK_CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[user_id] = (dek, time.monotonic() + DEK_CACHE_TTL_SECONDS)


def evict(user_id: str | None = None) -> None:
    with _cache_lock:
        if user_id is None:
            _cache.clear()
        else:
            _cache.pop(user_id, None)


def _decrypt_dek(user_id: str, encrypted_dek: bytes) -> bytes:
    dek = aws.client("kms").decrypt(CiphertextBlob=encrypted_dek, EncryptionContext=_context(user_id))
    return dek["Plaintext"]


def get_dek(db: Session, user_id: str) -> bytes:
    """기존 DEK를 반환한다. 없으면 KeyUnavailable(복호화 경로에서 새 키를 만들지 않는다)."""
    cached = _cache_get(user_id)
    if cached is not None:
        return cached
    row = db.scalar(select(UserKey).where(UserKey.user_id == user_id))
    if row is None:
        raise KeyUnavailable(user_id)
    dek = _decrypt_dek(user_id, row.encrypted_dek)
    _cache_put(user_id, dek)
    return dek


def get_or_create_dek(db: Session, user_id: str) -> bytes:
    """암호화 경로용. DEK가 없으면 KMS로 발급해 저장한다(동시 발급 시 먼저 저장된 키 사용)."""
    try:
        return get_dek(db, user_id)
    except KeyUnavailable:
        pass
    key_id = get_settings().kms_key_alias
    if not key_id:
        raise RuntimeError("KMS_KEY_ALIAS is not configured")
    generated = aws.client("kms").generate_data_key(
        KeyId=key_id, KeySpec="AES_256", EncryptionContext=_context(user_id)
    )
    db.execute(
        insert(UserKey)
        .values(user_id=user_id, encrypted_dek=generated["CiphertextBlob"], kms_key_id=key_id)
        .on_conflict_do_nothing(index_elements=[UserKey.user_id])
    )
    db.flush()
    return get_dek(db, user_id)


def destroy_user_key(db: Session, user_id: str) -> None:
    """DEK 폐기(crypto-shredding). 호출 후 해당 사용자의 암호문은 복호화할 수 없다."""
    db.execute(delete(UserKey).where(UserKey.user_id == user_id))
    evict(user_id)


def encrypt(dek: bytes, plaintext: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(NONCE_SIZE)
    return nonce + AESGCM(dek).encrypt(nonce, plaintext, aad)


def decrypt(dek: bytes, blob: bytes, aad: bytes) -> bytes:
    try:
        return AESGCM(dek).decrypt(blob[:NONCE_SIZE], blob[NONCE_SIZE:], aad)
    except Exception as e:  # cryptography.exceptions.InvalidTag 등
        raise DecryptionFailed() from e
