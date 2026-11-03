"""테스트 공통 픽스처.

개발 DB를 오염시키지 않도록 `<DB_NAME>_test` 데이터베이스를 세션 시작 시 새로 만들고,
Alembic 마이그레이션을 적용한 뒤 세션 종료 시 삭제한다.
"""
import os

# app 모듈이 import되며 엔진이 생성되기 전에 DB 이름을 바꿔야 한다.
_BASE_DB_NAME = os.environ["DB_NAME"]
TEST_DB_NAME = f"{_BASE_DB_NAME}_test"
os.environ["DB_NAME"] = TEST_DB_NAME

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.config import get_settings  # noqa: E402


def _admin_engine():
    # CREATE/DROP DATABASE는 트랜잭션 밖에서 실행해야 하므로 AUTOCOMMIT
    url = get_settings().database_url.set(database="postgres")
    return create_engine(url, isolation_level="AUTOCOMMIT")


@pytest.fixture(scope="session", autouse=True)
def test_database():
    admin = _admin_engine()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))

    command.upgrade(Config("/srv/alembic.ini"), "head")
    yield

    from app.db import engine

    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(autouse=True)
def _no_background_personal_index(monkeypatch):
    """저장 즉시 색인(B5)의 백그라운드 스레드를 테스트에서 끈다.

    로컬 .env의 EMBEDDING_URL을 테스트도 읽기 때문에, 끄지 않으면 저장마다 실제 임베더를 부른다.
    색인 동작 자체는 test_personal_index_b5가 대역으로 검사한다.
    """
    from app.features import personal_index

    monkeypatch.setattr(personal_index, "submit", lambda items: None)


@pytest.fixture(autouse=True)
def _no_real_embedder(monkeypatch):
    """로컬 .env의 EMBEDDING_URL을 시험이 읽어 실제 임베더를 부르지 않게 한다(11-03, docs/C6.md).
    임베더가 꺼져 있으면 배치 재시도(최악 ~8분)를 기다리며 시험이 멈췄다.
    임베더가 필요한 시험은 대역을 넘기거나 `get_settings().embedding_url`을 바꾼다(test_embedder_http)."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "embedding_url", "")


@pytest.fixture
def db_session():
    """테스트마다 트랜잭션을 열고 끝나면 롤백한다. 테스트 안의 commit은 SAVEPOINT로 처리된다."""
    from sqlalchemy.orm import Session

    from app.db import engine

    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c
