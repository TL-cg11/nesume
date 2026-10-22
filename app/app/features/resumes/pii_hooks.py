"""B 문서 공용 PII 처리 (part2_guide 4.6, 4.8, 4.26, 4.33).

자소서 본문·경험 데이터는 PII 토큰화 상태로 저장하고, 원문은 B7 대응표(pii_vaults)에만 둔다.
- 판정: A1 `validate_input` — 주민번호·계좌번호 등은 저장 자체를 거부(B4·B5)
- 저장: A1 `tokenize_fields(..., ttl_seconds=None)` + `SessionVaultStore` — 대응표는 문서와 같은 트랜잭션
- 복원: A1 `detokenize_fields` — 소유자 본인 요청일 때만(tasks B7), 원문 그대로(조사 보정 끔)

A1 함수는 async라서 동기 서비스에서 `_run`으로 실행한다. 대응표 저장은 세션에 대한 동기 작업뿐이라
같은 스레드에서 순차로 끝난다.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from sqlalchemy.orm import Session

from app.pii import detokenize_fields, tokenize_fields, validate_input
from app.pii.pg_vault_store import SessionVaultStore, delete_in

FieldValue = str | list[str]
T = TypeVar("T")
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pii")


class SensitiveInputBlocked(ValueError):
    """주민번호·계좌번호 등 저장이 금지된 민감정보가 포함됨(A1 판정)."""


class NotOwner(PermissionError):
    """소유자가 아닌 요청자에게는 원문을 복원하지 않는다."""


def _run(coro) -> T:
    """동기 코드에서 A1 코루틴을 실행한다. 이미 이벤트 루프 안이면(예: async 호출자) 별도 스레드에서."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return _executor.submit(asyncio.run, coro).result()


def ensure_no_sensitive(text: str) -> None:
    """민감정보가 있으면 SensitiveInputBlocked. 입력 값은 예외에 담지 않는다."""
    if not validate_input(text).ok:
        raise SensitiveInputBlocked()


def protect_fields(db: Session, owner_id: str, fields: dict[str, FieldValue]) -> tuple[dict[str, FieldValue], str | None]:
    """민감정보 판정 → 토큰화 → 대응표 저장(같은 트랜잭션).

    반환: (토큰화된 필드, 대응표 ID). 개인정보가 없으면 대응표를 만들지 않고 ID는 None.
    None 값 필드는 건드리지 않는다.
    """
    present = {k: v for k, v in fields.items() if v is not None}
    for value in present.values():
        for text in (value if isinstance(value, list) else [value]):
            ensure_no_sensitive(text)
    if not present:
        return dict(fields), None
    result = _run(tokenize_fields(present, owner_id=owner_id, store=SessionVaultStore(db), ttl_seconds=None))
    vault_id = result.vault_id if result.counts else None
    return {**fields, **result.texts}, vault_id


def restore_fields(
    db: Session, owner_id: str, requester_id: str, fields: dict[str, FieldValue | None], vault_id: str | None
) -> dict[str, FieldValue | None]:
    """소유자 본인에게 원문으로 복원한다. 대응표가 없으면(개인정보 없음·이전 데이터) 그대로 반환."""
    if requester_id != owner_id:
        raise NotOwner()
    if vault_id is None:
        return dict(fields)
    present = {k: v for k, v in fields.items() if v is not None}
    result = _run(detokenize_fields(present, vault_id, owner_id, store=SessionVaultStore(db), fix_particles=False))
    return {**fields, **result.texts}


def discard_vault(db: Session, vault_id: str | None) -> None:
    """더 이상 참조되지 않는 대응표를 지운다(경험 수정 시 이전 대응표). 참조 행을 먼저 바꾼 뒤 호출."""
    if vault_id is not None:
        delete_in(db, vault_id)
        db.flush()
