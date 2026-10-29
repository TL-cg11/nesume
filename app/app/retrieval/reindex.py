"""C3 — 실제 임베딩으로 인덱스 채우기(배치). 가짜(데모) 벡터를 대신한다.

- 공고: 활성 공고마다 표시 필드를 이어 붙인 글 → `index_posting`(A1 mask → C5 → 임베딩).
- 개인: 자소서(문항별 최신 버전)·경험 → `index_personal`. **B가 저장한 토큰화 값 그대로**(원문 복원 안 함 —
  원문을 쓰면 PII가 `user_profile_embeddings.content`에 평문으로 들어간다). 등급·공유 메타는 원본에서 복제.

- 강좌(C14 의미 검색): 제목 + K-MOOC 요약 앞부분 → `learning_content_embeddings`(강좌당 1행, 공개).

셋 다 **바뀐 것만** 다시 임베딩한다: 만들 글을 계산해 저장된 `content`와 같으면 건너뛴다(임베딩 호출 0).
바뀌면 그 문서의 행을 지우고 새로 넣는다(같은 트랜잭션). 실행당 상한(`cap`)으로 임베딩 호출 수를 묶는다.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.embedding import (
    MODEL_VERSION,
    JobPostingEmbedding,
    LearningContentEmbedding,
    UserProfileEmbedding,
)
from app.models.learning import LearningContent
from app.models.posting import JobPosting
from app.retrieval.embedder import Embedder
from app.retrieval.indexing import clean_posting_text, index_personal, index_posting

#: 실행당 임베딩 상한(CPU TEI 1~3 문서/s → 수 분 안)
DEFAULT_CAP = 500
#: 한 문서 글 길이 상한(bge-m3 8192 토큰, CPU 처리량 위해 짧게 — D20 README 512~1024 토큰 권장)
MAX_CHARS = 2000

_POSTING_FIELDS = (
    "title", "company_name", "job_name", "industry_name", "job_content",
    "certificates", "preferred", "major", "computer_skills", "career_text", "edu_text",
)


def posting_text(p: JobPosting) -> str:
    """공고 → 임베딩할 원문(필드 이어 붙임, 길이 상한). 비면 빈 문자열."""
    parts = [str(v).strip() for v in (getattr(p, f) for f in _POSTING_FIELDS) if v and str(v).strip()]
    return "\n".join(parts)[:MAX_CHARS]


def _stored(session: Session, model, source_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    """source_id → 저장된 0번 청크 content(같은 모델 버전만)."""
    ids = list(source_ids)
    if not ids:
        return {}
    rows = session.execute(
        select(model.source_id, model.content).where(
            model.source_id.in_(ids), model.chunk_index == 0, model.model_version == MODEL_VERSION
        )
    )
    return {sid: content for sid, content in rows}


def reindex_postings(session: Session, embedder: Embedder, *, cap: int = DEFAULT_CAP) -> dict:
    """활성 공고 중 벡터가 없거나 글이 바뀐 것(데모 벡터 포함)을 다시 임베딩."""
    postings = session.execute(select(JobPosting).where(JobPosting.is_active.is_(True))).scalars().all()
    stored = _stored(session, JobPostingEmbedding, (p.id for p in postings))
    done = unchanged = empty = 0
    for p in postings:
        raw = posting_text(p)
        if not raw:
            empty += 1
            continue
        if stored.get(p.id) == clean_posting_text(raw):
            unchanged += 1
            continue
        if done >= cap:
            continue
        session.execute(delete(JobPostingEmbedding).where(JobPostingEmbedding.source_id == p.id))
        index_posting(session, embedder, source_id=p.id, raw_text=raw)
        done += 1
    pending = len(postings) - done - unchanged - empty
    return {"embedded": done, "unchanged": unchanged, "empty": empty, "pending": pending}


def reindex_personal(session: Session, embedder: Embedder, *, cap: int = DEFAULT_CAP) -> dict:
    """자소서·경험(삭제 안 된 것) 중 벡터가 없거나 바뀐 것을 다시 임베딩. 토큰화 값 그대로."""
    from app.features.experiences.reader import tokenized_experience_docs
    from app.features.resumes.reader import tokenized_resume_docs

    docs = [("resume", d) for d in tokenized_resume_docs(session)]
    docs += [("experience", d) for d in tokenized_experience_docs(session)]
    stored = _stored(session, UserProfileEmbedding, (d["id"] for _, d in docs))
    done = unchanged = empty = 0
    for source_type, d in docs:
        text = d["text"][:MAX_CHARS]
        if not text.strip():
            empty += 1
            continue
        if stored.get(d["id"]) == text:
            unchanged += 1
            continue
        if done >= cap:
            continue
        session.execute(delete(UserProfileEmbedding).where(UserProfileEmbedding.source_id == d["id"]))
        index_personal(
            session, embedder, owner_id=d["owner_id"], source_type=source_type, source_id=d["id"],
            text=text, grade=d["grade"], shared_with=d.get("shared_with") or [],
        )
        done += 1
    pending = len(docs) - done - unchanged - empty
    return {"embedded": done, "unchanged": unchanged, "empty": empty, "pending": pending}


#: 강좌는 짧은 글이라 한 번에 더 많이(로컬 CPU 실측 초당 6.6건 → 2,000건 약 5분). 첫 채움은 며칠에 나눈다.
CONTENT_CAP = 2000
#: K-MOOC 요약은 앞부분만(제목이 핵심, 요약은 맥락 보강)
CONTENT_SUMMARY_CHARS = 300


def content_text(c: LearningContent) -> str:
    """강좌 → 임베딩할 글. 고용24 `summary`는 기관·지역·기간(사실 정보)이라 의미가 없어 넣지 않는다."""
    if c.source == "kmooc" and c.summary:
        return f"{c.title} — {c.summary[:CONTENT_SUMMARY_CHARS]}"
    return c.title


def reindex_contents(session: Session, embedder: Embedder, *, cap: int = CONTENT_CAP) -> dict:
    """활성 강좌 중 벡터가 없거나 글이 바뀐 것을 임베딩(강좌당 1행 갱신). 공개 메타데이터라 PII 없음."""
    contents = session.execute(
        select(LearningContent).where(LearningContent.is_active.is_(True))
    ).scalars().all()
    stored = {
        r.content_id: r
        for r in session.execute(
            select(LearningContentEmbedding).where(LearningContentEmbedding.model_version == MODEL_VERSION)
        ).scalars()
    }
    todo, unchanged = [], 0
    for c in contents:
        text = content_text(c)
        row = stored.get(c.id)
        if row is not None and row.content == text:
            unchanged += 1
        else:
            todo.append((c, text))
    batch = todo[:cap]
    if batch:
        vecs = embedder.embed([t for _, t in batch])
        for (c, text), vec in zip(batch, vecs, strict=True):
            row = stored.get(c.id)
            if row is None:
                session.add(LearningContentEmbedding(content_id=c.id, content=text, embedding=vec))
            else:
                row.content, row.embedding = text, vec
    return {"embedded": len(batch), "unchanged": unchanged, "pending": len(todo) - len(batch)}
