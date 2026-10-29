"""C3 — 임베딩 파이프라인. 문서를 A1 처리 → bge-m3 임베딩 → 메타와 함께 인덱스에 적재.

- 공개(공고): A1 `mask` → C5 인젝션 전처리 → 임베딩 → 공개 인덱스(spec 4.1 순서).
- 개인(자소서·경험): **B가 저장 때 토큰화**한 값을 그대로 임베딩 → owner/shared/grade 메타.
- 삭제: source_id에 FK 없어(다형 참조) **B20 물리삭제가 `delete_personal` 호출**(B 확인, 2026-10-22).

임베딩 호출은 `Embedder` 주입(개발 LocalBgeM3Embedder / 운영 D 서비스).
개인 문서 PII는 B가 상류(저장)에서 토큰화하므로 C3는 mask 안 함(docs/C3.md). 공개(공고)만 mask(C4).
런타임 동작은 poc/c3_c6_e2e_poc.py로 검증.
"""
import uuid
from datetime import datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.models.embedding import JobPostingEmbedding, UserProfileEmbedding
from app.pii import mask
from app.retrieval.embedder import Embedder
from app.retrieval.preprocess import preprocess_external_text


def clean_posting_text(raw_text: str) -> str:
    """공고 원문 → 임베딩·저장할 텍스트(A1 mask → C5 전처리). 결정적이라 "바뀌었나" 비교에도 쓴다."""
    # pre.flags(인젝션 탐지 신호)는 감사 로그(B3)에 남기는 것을 권장
    return preprocess_external_text(mask(raw_text)).text


def index_posting(
    session: Session,
    embedder: Embedder,
    *,
    source_id: uuid.UUID,
    raw_text: str,
    chunk_index: int = 0,
) -> JobPostingEmbedding:
    """공고(외부 텍스트) 1청크 적재. A1 mask → C5 전처리 → 임베딩 → 공개 인덱스."""
    clean = clean_posting_text(raw_text)
    vec = embedder.embed([clean])[0]
    row = JobPostingEmbedding(
        source_id=source_id, chunk_index=chunk_index, content=clean, embedding=vec
    )
    session.add(row)
    return row


def index_personal(
    session: Session,
    embedder: Embedder,
    *,
    owner_id: str,
    source_type: str,  # "resume" / "experience"
    source_id: uuid.UUID,
    text: str,
    grade: str = "personal",
    shared_with: list[dict] | None = None,
    chunk_index: int = 0,
) -> UserProfileEmbedding:
    """자소서·경험 1청크 적재 → owner/shared/grade 메타와 개인 인덱스.

    `text`는 **B가 저장 때 이미 토큰화한 값**([[PHONE_1]], pii_hooks)이라 C3는 그대로 임베딩한다
    (mask·C5 안 거침 — PII는 B가 상류에서 처리, docs/C3.md).
    """
    vec = embedder.embed([text])[0]
    row = UserProfileEmbedding(
        owner_id=owner_id,
        source_type=source_type,
        source_id=source_id,
        chunk_index=chunk_index,
        content=text,
        grade=grade,
        shared_with=shared_with or [],
        embedding=vec,
    )
    session.add(row)
    return row


def sync_shared_with(session: Session, *, source_id: uuid.UUID, shared_with: list[dict] | None) -> None:
    """자소서 공유 변경(B10) 시 해당 자소서의 모든 임베딩 행 `shared_with`를 갱신한다.

    복제(denormalize)한 `shared_with`가 원본 `resumes`와 어긋나면 **접근통제 실패**
    (권한 없는 멘토 열람 / 정당한 공유 차단)이므로, B10 공유 변경과 **같은 트랜잭션**에서
    이 훅을 호출해야 한다(docs/C3.md #1 ①). 멱등 — 같은 값으로 여러 번 호출해도 안전.
    """
    session.execute(
        sa_update(UserProfileEmbedding)
        .where(UserProfileEmbedding.source_id == source_id)
        .values(shared_with=shared_with or [])
    )


def reconcile_shared_with(
    session: Session, *, authoritative: dict[uuid.UUID, list[dict]]
) -> int:
    """정합성 재검사 골격(일 1회 배치, docs/C3.md #1 ②).

    `authoritative` = {자소서 source_id: 원본 기준 shared_with}. 동기 갱신이 한 번이라도
    누락됐을 때를 대비해 **원본을 진실로** 벡터 행을 일괄 복구한다(멱등). 복구한 자소서 수를
    돌려준다 — 불일치 탐지·알림(심각도)은 호출측(B/D 로깅)에서. 원본 조회·대상 범위는 B 연동 시 확정.
    """
    for source_id, truth in authoritative.items():
        sync_shared_with(session, source_id=source_id, shared_with=truth)
    return len(authoritative)


def mark_personal_deleted(
    session: Session, *, source_id: uuid.UUID, deleted_at: datetime | None
) -> None:
    """원본(자소서·경험) **소프트 삭제**를 임베딩에 반영한다(B4·B5 삭제와 같은 트랜잭션, B 요청 2026-10-23).

    C6 검색은 `deleted_at IS NULL`만 보므로, 소프트 삭제가 임베딩에 반영 안 되면 물리 삭제(30일) 전까지
    지운 자소서·경험이 **검색에 계속 뜬다**(유출·오노출). `deleted_at=None`을 주면 복원(재노출)도 된다. 멱등.
    """
    session.execute(
        sa_update(UserProfileEmbedding)
        .where(UserProfileEmbedding.source_id == source_id)
        .values(deleted_at=deleted_at)
    )


def delete_personal(session: Session, *, source_id: uuid.UUID) -> None:
    """원본(자소서·경험) **물리 삭제** 시 해당 임베딩 제거(B20 물리삭제 / 수정 시 재인덱싱 연계)."""
    session.execute(sa_delete(UserProfileEmbedding).where(UserProfileEmbedding.source_id == source_id))


def delete_posting(session: Session, *, source_id: uuid.UUID) -> None:
    session.execute(sa_delete(JobPostingEmbedding).where(JobPostingEmbedding.source_id == source_id))
