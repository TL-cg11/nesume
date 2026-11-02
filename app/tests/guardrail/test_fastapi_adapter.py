"""가드레일을 HTTP 요청에 붙이는 어댑터 (B16 평가 러너 연결, 2026-10-26).

B 가 요청한 세 가지가 실제로 이어지는지 본다.
  ① 감사 로그가 남는가      ② request_id 가 HTTP X-Request-ID 와 같은가
  ③ 평가 트래픽이 구분되는가
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import CurrentUser, Role, get_current_user
from app.core.context import request_id_var
from app.core.request_id import RequestIdMiddleware
from app.features.writing.router import get_guardrail, router
from app.guardrail import Guardrail, LlmClient
from app.guardrail.fastapi import SESSION_HEADER, _as_uuid, build_context, guardrail_kwargs
from app.pii import InMemoryVaultStore
from tests.guardrail.fakes import FakeProvider

FULL = ("2025년 교내 프로젝트에서 예약 지연 문제를 맡게 되었습니다. "
        "저는 최선을 다했습니다. 캐시를 도입했고 그 결과 응답시간을 40% 단축했습니다.")


class RecordingSink:
    """감사 로그를 받아 적어 두기만 하는 가짜. DB 를 쓰지 않는다."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def write(self, **fields: object) -> None:
        self.rows.append(dict(fields))


def make_client(sink: RecordingSink) -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)   # X-Request-ID 를 실제로 세팅한다
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub="u1", role=Role.USER)
    app.dependency_overrides[get_guardrail] = lambda: Guardrail(
        llm=LlmClient(provider=FakeProvider(reply="")),
        vault=InMemoryVaultStore(),
        audit=sink,
    )
    return TestClient(app)


# ---------------------------------------------------------------- 요청 ID

def test_request_id_accepts_uuid_forms() -> None:
    raw = uuid.uuid4()
    assert _as_uuid(str(raw)) == raw
    assert _as_uuid(raw.hex) == raw, "미들웨어 기본값이 hex 라 이 형태가 들어온다"


def test_request_id_falls_back_when_not_a_uuid() -> None:
    """★ 헤더 형식은 UUID 가 아닌 값도 허용한다. 컬럼이 UUID 라 새로 만들 수밖에 없다."""
    assert isinstance(_as_uuid("not-a-uuid"), uuid.UUID)
    assert isinstance(_as_uuid(""), uuid.UUID)


def test_request_id_comes_from_the_current_request() -> None:
    raw = uuid.uuid4()
    token = request_id_var.set(raw.hex)
    try:
        ctx = build_context(feature="f", user_id="u1", role="user", session_id=None)
        assert ctx.request_id == raw
    finally:
        request_id_var.reset(token)


def test_audit_row_request_id_matches_the_http_header() -> None:
    """★ B16 러너가 요청과 로그를 잇는 근거다."""
    sink = RecordingSink()
    sent = uuid.uuid4()

    r = make_client(sink).post(
        "/writing/proofread",
        json={"text": FULL},
        headers={"X-Request-ID": str(sent)},
    )

    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == str(sent)
    assert len(sink.rows) == 1, "요청 하나당 감사 로그 한 줄"
    assert sink.rows[0]["request_id"] == sent


# ---------------------------------------------------------------- 평가 트래픽

def test_is_test_is_derived_from_the_session_prefix() -> None:
    """★ 하나에서 둘을 만들면 어긋날 수가 없다.

    `audit_logs` CHECK 제약이 (session_id LIKE 'test-%') = is_test 라 둘이 늘 같아야 한다.
    """
    assert build_context(feature="f", user_id="u", role="user", session_id="test-7").is_test is True
    assert build_context(feature="f", user_id="u", role="user", session_id="s-7").is_test is False
    assert build_context(feature="f", user_id="u", role="user", session_id=None).is_test is False


def test_evaluation_traffic_is_marked_in_the_audit_row() -> None:
    sink = RecordingSink()
    make_client(sink).post(
        "/writing/proofread",
        json={"text": FULL},
        headers={SESSION_HEADER: "test-b16-001"},
    )

    row = sink.rows[0]
    assert row["is_test"] is True
    assert row["session_id"] == "test-b16-001"


def test_normal_traffic_is_not_marked() -> None:
    sink = RecordingSink()
    make_client(sink).post(
        "/writing/proofread",
        json={"text": FULL},
        headers={SESSION_HEADER: "s-user-42"},
    )

    row = sink.rows[0]
    assert row["is_test"] is False
    assert row["session_id"] == "s-user-42"


def test_audit_row_is_written_without_a_session_header() -> None:
    """세션 없는 단발 요청도 기록은 남아야 한다."""
    sink = RecordingSink()
    make_client(sink).post("/writing/proofread", json={"text": FULL})

    assert len(sink.rows) == 1
    assert sink.rows[0]["session_id"] == ""


# ---------------------------------------------------------------- 입력 검사

def test_overlong_session_header_is_rejected_at_the_router() -> None:
    """★ 서비스 안쪽에서 터지면 사용자는 500 으로 본다. 여기서 400 으로 막는다."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        guardrail_kwargs(CurrentUser(sub="u1", role=Role.USER), "x" * 129)
    assert exc.value.status_code == 400


def test_kwargs_carry_everything_the_service_needs() -> None:
    kw = guardrail_kwargs(CurrentUser(sub="u1", role=Role.USER), "test-1")
    assert set(kw) == {"user_id", "role", "session_id", "is_test", "request_id"}
    assert kw["user_id"] == "u1"
    assert kw["is_test"] is True


def test_rule_only_request_leaves_no_audit_row() -> None:
    """★ 발견한 사실 — 규칙만 검사하는 요청(use_llm=false)은 가드레일을 지나지 않는다.

    감사 로그는 A8 파이프라인이 쓰므로, 모델을 부르지 않는 경로에는 한 줄도 남지 않는다.
    자소서 본문을 받아 처리했는데 기록이 없다는 뜻이라, **남겨야 하는지 팀 판단이 필요하다**
    (B16 러너는 LLM 경로를 쓰므로 측정에는 영향이 없다).
    """
    sink = RecordingSink()
    r = make_client(sink).post("/writing/proofread", json={"text": FULL, "use_llm": False})

    assert r.status_code == 200
    assert sink.rows == [], "지금은 남지 않는다 — 바뀌면 이 시험이 먼저 알려 준다"


# ---------------------------------------------------------------- C6 검색 주입

def test_shared_guardrail_wires_the_retriever_when_an_embedder_is_configured(monkeypatch) -> None:
    """★ C 요청(2026-11-02) — 사용자 요청 경로에서 개인 검색이 실제로 돈다.

    주입이 빠져 있으면 `retriever=None` 이라 C6 가 한 번도 불리지 않고,
    카나리(C12·C13) 탐지도 실제 경로에서는 돌지 않는다.
    """
    from app.guardrail import fastapi as adapter

    sentinel = object()
    monkeypatch.setattr("app.retrieval.embedder.get_embedder", lambda: sentinel)
    monkeypatch.setattr("app.retrieval.search.build_retriever", lambda e: ("retriever", e))
    adapter._shared.cache_clear()

    try:
        assert adapter._shared().retriever == ("retriever", sentinel)
    finally:
        adapter._shared.cache_clear()


def test_shared_guardrail_leaves_the_retriever_off_without_an_embedder(monkeypatch) -> None:
    """EMBEDDING_URL 이 없으면 `get_embedder()` 가 None → 검색 단계 생략(기존 동작)."""
    from app.guardrail import fastapi as adapter

    monkeypatch.setattr("app.retrieval.embedder.get_embedder", lambda: None)
    adapter._shared.cache_clear()

    try:
        assert adapter._shared().retriever is None
    finally:
        adapter._shared.cache_clear()
