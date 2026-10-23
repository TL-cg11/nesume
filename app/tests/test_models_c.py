"""C 소유 모델 정의 스모크 테스트.

모델을 실제 로드·매퍼 설정해 "인덱스가 없는 컬럼을 가리킴"·FK 미해소 같은 **정의 버그**를
CI에서 잡는다. 이 종류는 ruff·순수로직 테스트로 안 잡힌다
(UserProfileEmbedding 에 `embedding` 컬럼 누락 → ix_upe_hnsw 가 없는 컬럼 인덱싱, 2026-10-22 사고).
"""
from sqlalchemy.orm import configure_mappers

from app.models.embedding import JobPostingEmbedding, UserProfileEmbedding
from app.models.learning import LearningContent, LearningRoadmap, LearningRoadmapItem
from app.models.posting import CollectionRun, JobPosting

C_MODELS = (
    JobPosting,
    CollectionRun,
    JobPostingEmbedding,
    UserProfileEmbedding,
    LearningContent,
    LearningRoadmap,
    LearningRoadmapItem,
)


def test_c_models_configure():
    configure_mappers()  # FK·관계 미해소 시 예외


def test_index_columns_exist():
    # __table_args__ 인덱스가 참조하는 컬럼이 테이블에 실제 있어야 한다(없으면 create 시 터짐).
    for model in C_MODELS:
        table = model.__table__
        cols = set(table.columns.keys())
        for idx in table.indexes:
            missing = {c.name for c in idx.columns} - cols
            assert not missing, f"{table.name}: 인덱스 {idx.name} 가 없는 컬럼 {missing} 참조"


def test_embedding_tables_have_vector_column():
    for model in (JobPostingEmbedding, UserProfileEmbedding):
        assert "embedding" in model.__table__.columns, f"{model.__table__.name} 에 embedding 컬럼 없음"
