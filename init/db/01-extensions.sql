-- 로컬 최초 기동(빈 볼륨) 시에만 실행된다.
-- RDS에서는 실행되지 않으므로 동일 구문을 Alembic 첫 마이그레이션에도 둔다(기준은 마이그레이션).
CREATE EXTENSION IF NOT EXISTS vector;
