"""저장 즉시 개인 인덱스 반영 (tasks B5 "저장 후 C3로 개인 인덱스 반영", 11/2).

자소서 버전·문항이나 경험을 저장하면 그 문서 하나만 바로 임베딩해 `user_profile_embeddings`에 넣는다.
그래야 새로 쓴 자소서가 다음 수집 배치(dev 기준 하루 1회)를 기다리지 않고 공고 추천·검색에 쓰인다.

- 저장 요청은 '다시 색인할 문서'만 표시하고 바로 끝난다(`mark`).
  임베딩은 **DB 커밋 뒤** 백그라운드 스레드 하나가 처리한다
  — 임베더가 느리거나 꺼져 있어도 저장이 막히지 않는다. 롤백되면 아무것도 하지 않는다.
- 글 형식은 C3 배치(`retrieval.reindex.reindex_personal`)와 같다(토큰화 본문 그대로, 원문 복원 안 함).
  배치가 다시 봐도 '변경 없음'으로 건너뛴다. 실패하면 로그만 남기고 배치가 나중에 채운다.
- `EMBEDDING_URL`이 없으면(로컬 기본·테스트) 아무것도 하지 않는다.
"""
from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from sqlalchemy import delete, event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SourceType = Literal["resume", "experience"]
_KEY = "personal_index_pending"
#: 저장 즉시 색인은 짧게 기다린다(배치용 기본 60초·긴 재시도와 다르게). 실패분은 배치가 채운다
TIMEOUT_S = 10.0
MAX_RETRY_SLEEP_S = 1.0

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="personal-index")


def mark(db: Session, source_type: SourceType, source_id: uuid.UUID) -> None:
    """이 문서를 커밋 뒤에 다시 색인하도록 표시한다(같은 요청에서 여러 번 불러도 한 번)."""
    db.info.setdefault(_KEY, set()).add((source_type, source_id))


def _embedding_url() -> str | None:
    from app.config import get_settings

    return get_settings().embedding_url


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    pending = session.info.pop(_KEY, None)
    if pending and _embedding_url():
        submit(sorted(pending, key=str))


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_KEY, None)


def submit(items: list[tuple[SourceType, uuid.UUID]]) -> None:
    """백그라운드로 보낸다. 테스트는 이 함수를 바꿔 바로 실행한다."""
    _pool.submit(run, items)


def run(items: list[tuple[SourceType, uuid.UUID]]) -> None:
    from app.retrieval.embedder import EmbeddingError, HttpEmbedder

    url = _embedding_url()
    if not url:
        return
    embedder = HttpEmbedder(url, timeout_s=TIMEOUT_S, sleep=lambda s: time.sleep(min(s, MAX_RETRY_SLEEP_S)))
    for source_type, source_id in items:
        try:
            _run_one(embedder, source_type, source_id)
        except EmbeddingError as e:  # 임베더 꺼짐·오류: 저장은 이미 끝났다. 배치가 나중에 채운다
            logger.warning("personal_index_failed", extra={"source_type": source_type, "reason": str(e)})
        except Exception:  # noqa: BLE001 - 백그라운드 스레드에서 예외가 사라지지 않게 남긴다
            logger.exception("personal_index_error", extra={"source_type": source_type})


def _run_one(embedder, source_type: SourceType, source_id: uuid.UUID) -> str:
    """읽기 → 임베딩 → 쓰기. 임베더를 기다리는 동안 DB 세션을 잡지 않는다(마이그레이션·쓰기를 막지 않게)."""
    from app.db import SessionLocal

    with SessionLocal() as db:
        state, doc, text = _plan(db, source_type, source_id)
    if state != "embed":
        if state == "empty":
            with SessionLocal.begin() as db:
                _clear(db, source_id)
        return state
    vec = embedder.embed([text])[0]
    with SessionLocal.begin() as db:
        _write(db, _Fixed(vec), source_type, source_id, doc, text)
    return "embedded"


def index_one(db: Session, embedder, source_type: SourceType, source_id: uuid.UUID) -> str:
    """문서 하나를 배치와 같은 방식으로 색인(한 세션 안에서). 반환: embedded / unchanged / empty / gone."""
    state, doc, text = _plan(db, source_type, source_id)
    if state == "empty":
        _clear(db, source_id)
    elif state == "embed":
        _write(db, embedder, source_type, source_id, doc, text)
        return "embedded"
    return state


class _Fixed:
    """미리 받아 둔 벡터를 돌려주는 임베더(쓰기 단계에서 index_personal에 넘긴다)."""

    def __init__(self, vec):
        self._vec = vec

    def embed(self, texts):
        return [self._vec for _ in texts]


def _plan(db: Session, source_type: SourceType, source_id: uuid.UUID):
    """(상태, 문서, 글). 상태: embed / unchanged / empty / gone."""
    from app.features.experiences.reader import tokenized_experience_doc
    from app.features.resumes.reader import tokenized_resume_doc
    from app.models.embedding import UserProfileEmbedding
    from app.retrieval.reindex import MAX_CHARS, _stored

    build = tokenized_resume_doc if source_type == "resume" else tokenized_experience_doc
    doc = build(db, source_id)
    if doc is None:  # 삭제됨 — 검색 제외는 C3 mark_personal_deleted, 물리 삭제는 B20이 맡는다
        return "gone", None, None
    text = doc["text"][:MAX_CHARS]
    # 배치와 같은 기준(0번 청크·같은 모델 버전)
    stored = _stored(db, UserProfileEmbedding, [source_id]).get(source_id)
    if not text.strip():  # 내용을 다 지웠다 — 예전 벡터가 남아 엉뚱한 추천이 나오지 않게 지운다
        return "empty", doc, text
    if stored == text:
        return "unchanged", doc, text
    return "embed", doc, text


def _clear(db: Session, source_id: uuid.UUID) -> None:
    from app.models.embedding import UserProfileEmbedding

    db.execute(delete(UserProfileEmbedding).where(UserProfileEmbedding.source_id == source_id))


def _write(db: Session, embedder, source_type: SourceType, source_id: uuid.UUID, doc: dict,
           text: str) -> None:
    from app.retrieval.indexing import index_personal

    _clear(db, source_id)
    index_personal(db, embedder, owner_id=doc["owner_id"], source_type=source_type, source_id=source_id,
                   text=text, grade=doc["grade"], shared_with=doc["shared_with"])
