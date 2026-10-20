"""C3 — 임베딩 파이프라인. 문서를 A1 처리 → bge-m3 임베딩 → 메타와 함께 인덱스에 적재.

- 공개(공고): A1 `mask` → C5 인젝션 전처리 → 임베딩 → 공개 인덱스(spec 4.1 순서).
- 개인(자소서·경험): A1 `mask` → owner/shared/grade 메타와 개인 인덱스.
- 삭제: 원본 삭제 시 임베딩도 제거(B5 삭제·B20 물리삭제 연계).

임베딩 호출은 `Embedder` 주입(개발 LocalBgeM3Embedder / 운영 D 서비스).
개인 문서 PII를 mask vs tokenize로 할지는 docs/C3.md 미결정 — 현재 **mask**(임베딩 텍스트는 복원 불필요).
런타임 동작은 poc/c3_c6_e2e_poc.py로 검증.
"""
import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session

from app.pii import mask
from app.models.embedding import JobPostingEmbedding, UserProfileEmbedding
from app.retrieval.embedder import Embedder
from app.retrieval.preprocess import preprocess_external_text


def index_posting(
    session: Session,
    embedder: Embedder,
    *,
    source_id: uuid.UUID,
    raw_text: str,
    chunk_index: int = 0,
) -> JobPostingEmbedding:
    """공고(외부 텍스트) 1청크 적재. A1 mask → C5 전처리 → 임베딩 → 공개 인덱스."""
    pre = preprocess_external_text(mask(raw_text))
    # pre.flags(인젝션 탐지 신호)는 감사 로그(B3)에 남기는 것을 권장
    clean = pre.text
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
    raw_text: str,
    grade: str = "personal",
    shared_with: list[dict] | None = None,
    chunk_index: int = 0,
) -> UserProfileEmbedding:
    """자소서·경험 1청크 적재. A1 mask → 임베딩 → owner/shared/grade 메타와 개인 인덱스.

    내부 사용자 텍스트라 C5(외부 인젝션 전처리)는 거치지 않는다. PII는 A1 mask로 제거.
    """
    clean = mask(raw_text)
    vec = embedder.embed([clean])[0]
    row = UserProfileEmbedding(
        owner_id=owner_id,
        source_type=source_type,
        source_id=source_id,
        chunk_index=chunk_index,
        content=clean,
        grade=grade,
        shared_with=shared_with or [],
        embedding=vec,
    )
    session.add(row)
    return row


def delete_personal(session: Session, *, source_id: uuid.UUID) -> None:
    """원본(자소서·경험) 삭제 시 해당 임베딩 제거(B5 삭제 / B20 물리삭제 연계)."""
    session.execute(sa_delete(UserProfileEmbedding).where(UserProfileEmbedding.source_id == source_id))


def delete_posting(session: Session, *, source_id: uuid.UUID) -> None:
    session.execute(sa_delete(JobPostingEmbedding).where(JobPostingEmbedding.source_id == source_id))
