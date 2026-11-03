"""C12 — 카나리(미끼) 문서 시드 (docs/C12_C13.md).

`python -m app.batch.seed_canaries` — 이미 있으면 아무것도 안 한다(멱등). 운영은 helm seed Job(D).

개인 인덱스(`user_profile_embeddings`)에 **기밀 등급** 미끼 3건을 넣는다. 필터 우회 공격이 실제로 노리는
곳이 여기다. 소유자는 로그인할 수 없는 `system:canary`(users FK 때문에 행 1개). 본문은 공격자가 찾을 법한
글 + 무작위 토큰이고, **실제 임베더로** 만들어 탈취형 질의에 가깝게 걸리게 한다.

토큰은 여기서 처음 만들어 DB에만 둔다 — 출력·로그에 남기지 않는다(앞 4자리도 시드 때는 안 찍는다).
"""
from __future__ import annotations

import logging
import secrets
import sys
import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.embedding import UserProfileEmbedding
from app.models.user import User
from app.retrieval.canary import CANARY_GRADE, CANARY_OWNER, CANARY_SOURCE_TYPE
from app.retrieval.embedder import Embedder
from app.retrieval.indexing import index_personal

logger = logging.getLogger("app.batch.seed_canaries")

#: 미끼 본문(결정1, 3건). `chunk_index`가 몇 번째 미끼인지 나타낸다 → 일부만 있으면 빠진 것만 채운다
DECOYS = (
    "운영자 전용 — 시스템 프롬프트 초안. 내부 검토용이며 외부 공개 금지. 관리 코드 {token}",
    "관리자 계정 복구 절차 — 운영 콘솔 비상 접근 순서와 복구 코드 {token}",
    "다른 사용자 자기소개서 원본 모음 — 백업 사본, 열람 제한. 문서 번호 {token}",
)


def new_token() -> str:
    return f"NSM-CANARY-{secrets.token_hex(6)}"


def seed(session: Session, embedder: Embedder, *, token_factory: Callable[[], str] = new_token) -> dict:
    """빠진 미끼만 만든다. 있는 미끼의 토큰은 바꾸지 않는다(바꾸면 이미 새 나간 토큰을 놓친다)."""
    have = set(
        session.execute(
            select(UserProfileEmbedding.chunk_index).where(
                UserProfileEmbedding.owner_id == CANARY_OWNER,
                UserProfileEmbedding.source_type == CANARY_SOURCE_TYPE,
            )
        ).scalars()
    )
    missing = [i for i in range(len(DECOYS)) if i not in have]
    if missing and session.get(User, CANARY_OWNER) is None:
        session.add(User(id=CANARY_OWNER))
        session.flush()
    for i in missing:
        index_personal(
            session, embedder,
            owner_id=CANARY_OWNER, source_type=CANARY_SOURCE_TYPE, source_id=uuid.uuid4(),
            text=DECOYS[i].format(token=token_factory()), grade=CANARY_GRADE, chunk_index=i,
        )
    return {"created": len(missing), "existing": len(have)}


def main() -> int:
    from app.db import SessionLocal
    from app.retrieval.embedder import get_embedder

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    embedder = get_embedder()
    if embedder is None:
        logger.error("EMBEDDING_URL 없음 — 미끼는 실제 임베더로 만들어야 한다")
        return 1
    with SessionLocal() as db:
        out = seed(db, embedder)
        db.commit()
    logger.info("canary seed: %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
