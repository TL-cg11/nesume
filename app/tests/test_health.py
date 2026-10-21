from sqlalchemy import text


def test_health_returns_200(client):
    r = client.get("/health")
    assert r.status_code == 200
    # 응답 전체를 고정하지 않는다. D4가 배포 확인용 version 등 필드를 추가한다.
    assert r.json()["status"] == "ok"


def test_ready_checks_db_vector_and_s3(client):
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["vector"] != "missing"
    assert body["checks"]["s3"] == "ok"


def test_runs_against_isolated_test_database():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.db import engine
    from tests.conftest import TEST_DB_NAME

    head = ScriptDirectory.from_config(Config("/srv/alembic.ini")).get_current_head()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT current_database()")).scalar() == TEST_DB_NAME
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == head
