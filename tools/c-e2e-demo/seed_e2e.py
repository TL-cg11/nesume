"""로컬 E2E 시드 — 공고 추천/학습 로드맵이 실제 데이터로 결과를 내게 한다.
임베딩 모델(D 서빙)이 없어 벡터는 '심는다'(랭킹이 나오게 결정적으로 구성).
DB·pgvector 검색·키워드매칭·권한·콘텐츠매칭은 전부 실제 코드 경로로 돈다.

실행: docker compose exec -T app python - <SUB> < seed_e2e.py
"""
import math
import sys
import uuid

from app.db import SessionLocal
from app.models.embedding import EMBED_DIM, JobPostingEmbedding, UserProfileEmbedding
from app.models.learning import LearningContent
from app.models.posting import JobPosting

SUB = sys.argv[1] if len(sys.argv) > 1 else "12708b06-5786-404b-abdc-fd146167ab86"


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


A, B = _unit(1), _unit(2)  # 두 '주제' 방향(거의 직교)
USER_VEC = A  # 사용자 프로필 = A 쪽
# 공고별 벡터: A에 가까울수록 상위
POSTINGS = [
    dict(title="클라우드 보안 엔지니어", job_name="정보보안", job_code="024",
         computer_skills="AWS, Docker, Linux, IAM, Kubernetes",
         job_content="AWS 클라우드 환경에서 IAM 최소권한 설계, Docker 컨테이너 운영, Linux 서버 보안을 담당합니다.",
         preferred="Kubernetes 운영 경험, 보안관제(SOC) 경험 우대",
         certificates="AWS Certified Security, 정보보안기사",
         region_code="11", region_name="서울", vec=_mix(A, B, 1.0, 0.0)),
    dict(title="DevSecOps 엔지니어", job_name="플랫폼", job_code="024",
         computer_skills="Docker, Kubernetes, AWS, CI/CD, Terraform",
         job_content="컨테이너 기반 배포 파이프라인(CI/CD)과 IaC(Terraform)를 운영하며 보안 게이트를 통합합니다.",
         preferred="AWS, Linux 운영 경험 우대",
         certificates="CKA, AWS SAA",
         region_code="11", region_name="서울", vec=_mix(A, B, 0.7, 0.3)),
    dict(title="클라우드 인프라 엔지니어", job_name="인프라", job_code="024",
         computer_skills="AWS, Terraform, Linux, Network",
         job_content="VPC/네트워크 설계와 Terraform 기반 인프라 자동화를 수행합니다.",
         preferred="Docker 경험 우대",
         certificates="AWS SAP",
         region_code="41", region_name="경기", vec=_mix(A, B, 0.4, 0.6)),
    dict(title="보안관제(SOC) 분석가", job_name="보안관제", job_code="024",
         computer_skills="SIEM, Linux, Network, 로그분석",
         job_content="SIEM 기반 이상징후 탐지와 로그 분석, 침해대응을 수행합니다.",
         preferred="클라우드 보안 이해 우대",
         certificates="정보보안기사",
         region_code="11", region_name="서울", vec=_mix(A, B, 0.1, 0.9)),
]

LEARNING = [
    dict(source="kmooc", external_id="kmooc-aws-1", mode="online", title="AWS 클라우드 입문",
         url="https://www.kmooc.kr/", provider="K-MOOC", est_hours=3.0, weeks=2,
         summary="클라우드 개념, EC2, IAM, 리전과 가용영역", certificate=True,
         competency_keys=["aws", "iam"]),
    dict(source="work24", external_id="w24-aws-lab", mode="offline", title="AWS 실무 (국비 훈련)",
         url="https://www.work24.go.kr/", provider="직업전문학교", est_hours=4.0, weeks=4,
         summary="콘솔 실습, VPC, 보안그룹, SSH", certificate=True,
         competency_keys=["aws", "network"]),
    dict(source="kmooc", external_id="kmooc-docker-1", mode="online", title="Docker & 컨테이너 기초",
         url="https://www.kmooc.kr/", provider="K-MOOC", est_hours=3.0, weeks=2,
         summary="이미지와 컨테이너, Dockerfile, 포트 매핑", certificate=False,
         competency_keys=["docker"]),
    dict(source="kmooc", external_id="kmooc-k8s-1", mode="online", title="Kubernetes 입문",
         url="https://www.kmooc.kr/", provider="K-MOOC", est_hours=4.0, weeks=3,
         summary="파드, 디플로이먼트, 서비스, 스케일링", certificate=False,
         competency_keys=["kubernetes"]),
    dict(source="work24", external_id="w24-linux", mode="offline", title="리눅스 시스템 운영",
         url="https://www.work24.go.kr/", provider="한국폴리텍", est_hours=3.0, weeks=3,
         summary="사용자/권한, 프로세스, 네트워크, 로그", certificate=True,
         competency_keys=["linux"]),
    dict(source="kmooc", external_id="kmooc-tf", mode="online", title="Terraform로 IaC 시작하기",
         url="https://www.kmooc.kr/", provider="K-MOOC", est_hours=2.0, weeks=2,
         summary="HCL 문법, provider, state, 모듈", certificate=False,
         competency_keys=["terraform", "aws"]),
    dict(source="kmooc", external_id="kmooc-git", mode="online", title="Git & GitHub 협업",
         url="https://www.kmooc.kr/", provider="K-MOOC", est_hours=2.0, weeks=1,
         summary="브랜치, 머지, PR, 충돌 해결", certificate=False,
         competency_keys=["git"]),
]


def main():
    s = SessionLocal()
    try:
        # 멱등: 기존 시드 제거(이 테스트 사용자/출처만)
        s.query(UserProfileEmbedding).filter_by(owner_id=SUB).delete()
        existing = s.query(JobPosting).filter(JobPosting.link_key.like("e2e-%")).all()
        for p in existing:
            s.delete(p)  # CASCADE로 임베딩 함께 삭제
        s.query(LearningContent).filter(LearningContent.external_id.like("kmooc-%")).delete()
        s.query(LearningContent).filter(LearningContent.external_id.like("w24-%")).delete()
        s.flush()

        # 공고 + 공개 임베딩
        for i, p in enumerate(POSTINGS, 1):
            vec = p.pop("vec")
            posting = JobPosting(
                source="work24_open",
                link_key=f"e2e-{i:03d}",
                content_hash=f"e2e-hash-{i:03d}",
                is_active=True,
                needs_review=False,
                **p,
            )
            s.add(posting)
            s.flush()
            s.add(JobPostingEmbedding(
                source_id=posting.id,
                chunk_index=0,
                content=f"{p['title']} {p['job_content']} {p['computer_skills']}",
                embedding=vec,
            ))

        # 사용자 프로필 임베딩(쿼리 벡터)
        s.add(UserProfileEmbedding(
            owner_id=SUB,
            source_type="resume",
            source_id=uuid.uuid4(),
            chunk_index=0,
            content="AWS와 Docker로 보안 인프라를 운영한 경험",
            embedding=USER_VEC,
        ))

        # 학습 콘텐츠
        for c in LEARNING:
            s.add(LearningContent(**c))

        s.commit()
        n_post = s.query(JobPosting).filter(JobPosting.link_key.like("e2e-%")).count()
        n_jpe = s.query(JobPostingEmbedding).count()
        n_upe = s.query(UserProfileEmbedding).filter_by(owner_id=SUB).count()
        n_lc = s.query(LearningContent).count()
        print(f"OK  공고={n_post} 공개임베딩={n_jpe} 프로필임베딩={n_upe} 학습콘텐츠={n_lc}")
    finally:
        s.close()


if __name__ == "__main__":
    main()
