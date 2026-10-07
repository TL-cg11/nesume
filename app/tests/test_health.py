from sqlalchemy import text


def test_health_returns_200(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_checks_db_vector_and_s3(client):
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["vector"] != "missing"
    assert body["checks"]["s3"] == "ok"


def test_runs_against_isolated_test_database():
    from app.db import engine
    from tests.conftest import TEST_DB_NAME

    with engine.connect() as conn:
        assert conn.execute(text("SELECT current_database()")).scalar() == TEST_DB_NAME
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0001"
