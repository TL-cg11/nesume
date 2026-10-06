"""init: enable pgvector

Revision ID: 0001
Revises:
Create Date: 2026-10-06

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # RDS에서는 init SQL이 실행되지 않으므로 확장 활성화의 기준은 이 마이그레이션이다.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
