"""로컬 데모 전용 — 수집한 **실제** 고용24 공채속보 공고에 합성 벡터를 붙여 추천 화면에 뜨게 한다.

운영 임베더(D bge-m3 서빙)가 없어 실제 공고는 임베딩이 없고, 그래서 추천(벡터 검색)에 안 뜬다.
이 스크립트는 `seed_e2e.py`와 같은 '주제 방향' 벡터를 써서, IT 관련 공고일수록 데모 사용자 벡터(A)에
가깝게 둔다. **추천 순서는 의미 없음**(진짜 임베딩 아님) — 원문 링크·출처 표시를 화면에서 보려는 용도.
제품 코드 아님. 운영은 C3 `index_posting`(실 임베더) 경로로 간다.

멱등: `[DEMO]`로 시작하는 공고 임베딩만 지우고 다시 만든다(실 임베딩·e2e 시드는 안 건드림).
실행: docker compose exec -T app python - < tools/c-e2e-demo/embed_work24_open_demo.py
"""
import math

from app.db import SessionLocal
from app.models.embedding import EMBED_DIM, JobPostingEmbedding
from app.models.posting import JobPosting

_IT = ("소프트웨어", "SW", "개발", "IT", "정보", "보안", "클라우드", "데이터", "AI", "인공지능", "전산", "네트워크", "시스템")


def _unit(seed: int) -> list[float]:
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


A = _unit(1)  # seed_e2e.py의 사용자 프로필 방향과 같다


def _it_score(p: JobPosting) -> float:
    text = " ".join(filter(None, (p.title, p.job_name, p.job_content)))
    hits = sum(1 for k in _IT if k in text)
    return min(hits / 4, 1.0)


def main():
    s = SessionLocal()
    try:
        s.query(JobPostingEmbedding).filter(JobPostingEmbedding.content.like("[DEMO]%")).delete(
            synchronize_session=False
        )
        postings = (
            s.query(JobPosting)
            .filter(JobPosting.source == "work24_open", JobPosting.is_active.is_(True))
            .filter(~JobPosting.link_key.like("e2e-%"))
            .all()
        )
        n = 0
        for i, p in enumerate(postings):
            w = 0.25 + 0.6 * _it_score(p)  # IT 관련일수록 A 쪽(0.25~0.85)
            vec = _mix(A, _unit(10_000 + i), w, 1 - w)
            s.add(JobPostingEmbedding(source_id=p.id, chunk_index=0, content=f"[DEMO] {p.title}", embedding=vec))
            n += 1
        s.commit()
        with_link = sum(1 for p in postings if p.source_url)
        print(f"데모 벡터 부착: {n}건 (원문 링크 있음 {with_link}건)")
    finally:
        s.close()


if __name__ == "__main__":
    main()
