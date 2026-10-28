"""로컬 데모 전용 합성 벡터 — 운영 임베더(D bge-m3 서빙)가 없을 때 추천 화면을 띄우기 위한 것.

추천은 벡터 검색이라 ① 사용자 프로필 벡터 ② 공고 벡터가 있어야 결과가 나온다. 둘 다 진짜 임베딩이 없으니
같은 '주제 방향'(A)을 기준으로 **결정적 합성 벡터**를 심는다. IT 관련 공고일수록 A에 가깝게 둔다.
**추천 순서는 의미 없음** — 원문 링크·출처 표시·화면 흐름 확인용. 제품 코드 아님.
D 임베더가 연결되면 C3 경로(`index_posting`·`index_personal`)가 대신하므로 이 스크립트는 삭제한다.

멱등: `[DEMO]`로 시작하는 임베딩만 지우고 다시 만든다(실 임베딩은 안 건드림).
실행(먼저 `python -m app.batch.jobs_collector --source work24_open`로 실제 공고 수집):
  docker compose exec -T app python - <사용자 sub> < tools/c-e2e-demo/demo_vectors.py
"""
import math
import sys
import uuid

from app.db import SessionLocal
from app.models.embedding import EMBED_DIM, JobPostingEmbedding, UserProfileEmbedding
from app.models.posting import JobPosting

_IT = ("소프트웨어", "SW", "개발", "IT", "정보", "보안", "클라우드", "데이터", "AI", "인공지능", "전산", "네트워크", "시스템")
_MARK = "[DEMO]"


def _unit(seed: int) -> list[float]:
    """결정적 의사난수 단위벡터(1024차원). 고차원이라 서로 거의 직교."""
    x, v = seed * 2654435761 % (2**31), []
    for _ in range(EMBED_DIM):
        x = (1103515245 * x + 12345) % (2**31)
        v.append(x / 2**31 - 0.5)
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v]


def _mix(a, b, wa, wb):
    v = [wa * x + wb * y for x, y in zip(a, b)]
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v]


A = _unit(1)  # 데모 사용자 프로필 방향


def _it_score(p: JobPosting) -> float:
    text = " ".join(filter(None, (p.title, p.job_name, p.job_content)))
    return min(sum(1 for k in _IT if k in text) / 4, 1.0)


def main(sub: str) -> None:
    s = SessionLocal()
    try:
        s.query(JobPostingEmbedding).filter(JobPostingEmbedding.content.like(f"{_MARK}%")).delete(
            synchronize_session=False
        )
        s.query(UserProfileEmbedding).filter(
            UserProfileEmbedding.owner_id == sub, UserProfileEmbedding.content.like(f"{_MARK}%")
        ).delete(synchronize_session=False)

        # ① 사용자 프로필 벡터(추천 쿼리)
        s.add(UserProfileEmbedding(
            owner_id=sub,
            source_type="resume",
            source_id=uuid.uuid4(),
            chunk_index=0,
            content=f"{_MARK} AWS와 Docker로 보안 인프라를 운영한 경험",
            embedding=A,
        ))

        # ② 실제 공고(활성)마다 공고 벡터
        postings = s.query(JobPosting).filter(JobPosting.is_active.is_(True)).all()
        for i, p in enumerate(postings):
            w = 0.25 + 0.6 * _it_score(p)  # IT 관련일수록 A 쪽(0.25~0.85)
            s.add(JobPostingEmbedding(
                source_id=p.id,
                chunk_index=0,
                content=f"{_MARK} {p.title}",
                embedding=_mix(A, _unit(10_000 + i), w, 1 - w),
            ))
        s.commit()
        print(f"데모 벡터: 프로필 1건(owner={sub}) + 공고 {len(postings)}건"
              f" (원문 링크 있음 {sum(1 for p in postings if p.source_url)}건)")
    finally:
        s.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("사용법: ... python - <사용자 sub> < demo_vectors.py")
    main(sys.argv[1])
