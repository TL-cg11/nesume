"""D3 공통 골격 검증: request_id, 에러 형식, health version."""
import re

import pytest
from fastapi.testclient import TestClient

from app.core.errors import NotFoundError
from app.main import app

HEX32 = re.compile(r"^[0-9a-f]{32}$")


@pytest.fixture
def raw_client():
    """500 응답 본문을 검사하기 위해 서버 예외를 올리지 않는 클라이언트."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_health_returns_ok_and_version(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["version"] == "dev"


def test_request_id_is_generated_when_missing(client: TestClient):
    r = client.get("/health")
    assert HEX32.match(r.headers["X-Request-ID"])


def test_request_id_is_echoed_when_valid(client: TestClient):
    r = client.get("/health", headers={"X-Request-ID": "trace-abc.123:xyz"})
    assert r.headers["X-Request-ID"] == "trace-abc.123:xyz"


def test_request_id_is_replaced_when_invalid(client: TestClient):
    r = client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert HEX32.match(r.headers["X-Request-ID"])


def test_404_keeps_fastapi_default_detail_and_has_request_id_header(client: TestClient):
    r = client.get("/no-such-path")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}  # HTTPException 응답은 건드리지 않는다(B 호환)
    assert HEX32.match(r.headers["X-Request-ID"])


def test_validation_error_hides_input(client: TestClient):
    @app.get("/_t/validate")
    def _validate(n: int) -> dict:
        return {"n": n}

    r = client.get("/_t/validate", params={"n": "secret-raw-value"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert body["detail"]
    assert body["request_id"] == r.headers["X-Request-ID"]
    assert body["errors"][0]["loc"] == ["query", "n"]
    assert "input" not in body["errors"][0]
    assert "secret-raw-value" not in r.text


def test_app_error_subclass_maps_status_and_code(client: TestClient):
    @app.get("/_t/missing")
    def _missing() -> dict:
        raise NotFoundError("자소서를 찾을 수 없습니다.")

    r = client.get("/_t/missing")
    assert r.status_code == 404
    assert r.json() == {
        "detail": "자소서를 찾을 수 없습니다.",
        "code": "not_found",
        "request_id": r.headers["X-Request-ID"],
    }


def test_unhandled_exception_is_masked(raw_client: TestClient):
    @app.get("/_t/boom")
    def _boom() -> dict:
        raise RuntimeError("db password is hunter2")

    r = raw_client.get("/_t/boom")
    assert r.status_code == 500
    assert r.json()["code"] == "internal_error"
    assert "hunter2" not in r.text
