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
from app.core.errors import register_exception_handlers
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


def make_client(sink: RecordingSink, user: CurrentUser | None = None) -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)   # X-Request-ID 를 실제로 세팅한다
    register_exception_handlers(app)          # 403 을 D3 형식으로 돌려준다
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user or CurrentUser(sub="u1", role=Role.USER)
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
        ctx = build_context(
            feature="f", user_id="u1", role="user", session_id=None, is_test=False
        )
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

def ctx(session_id, *, is_test):
    return build_context(
        feature="f", user_id="u", role="user", session_id=session_id, is_test=is_test
    )


def test_is_test_comes_from_the_token_not_the_header() -> None:
    """★ 사용자가 고칠 수 없는 값이 정해야 평가 지표를 사용자가 흔들 수 없다.

    2026-10-26 에는 D7 이 없어 세션 접두어로 판단했다. 그때는 일반 사용자가
    `test-` 로 시작하는 세션을 보내면 자기 트래픽을 지표에서 뺄 수 있었다.
    """
    assert ctx("test-7", is_test=False).is_test is False, "헤더를 흉내 내도 소용없다"
    assert ctx("s-7", is_test=True).is_test is True, "토큰이 평가 계정이면 평가 트래픽이다"


def test_session_prefix_follows_the_token() -> None:
    """★ `audit_logs` CHECK 가 (session_id LIKE 'test-%') = is_test 로 양방향이다.

    어긋나면 INSERT 가 거부되고, 그 거부는 요청이 끝난 뒤 finally 에서 터진다.
    받은 헤더를 그대로 믿지 않고 여기서 맞추면 어긋날 수가 없다.
    """
    assert ctx("s-7", is_test=True).session_id == "test-s-7", "평가 계정이면 붙인다"
    assert ctx("test-7", is_test=False).session_id == "7", "평가 계정이 아니면 뗀다"
    assert ctx("s-7", is_test=False).session_id == "s-7"


def test_test_account_without_a_session_gets_one() -> None:
    """접두어만 있는 세션("test-")은 서로 구분이 안 된다."""
    made = ctx(None, is_test=True).session_id
    assert made.startswith("test-") and len(made) > len("test-")


def test_evaluation_traffic_is_marked_in_the_audit_row() -> None:
    sink = RecordingSink()
    evaluator = CurrentUser(sub="b16", role=Role.USER, is_test=True)
    make_client(sink, evaluator).post(
        "/writing/proofread",
        json={"text": FULL},
        headers={SESSION_HEADER: "b16-001"},
    )

    row = sink.rows[0]
    assert row["is_test"] is True
    assert row["session_id"] == "test-b16-001", "접두어는 토큰에 맞춰 붙는다"


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


def test_normal_user_cannot_fake_evaluation_traffic() -> None:
    """★ 지표를 사용자가 흔들 수 없어야 한다."""
    sink = RecordingSink()
    make_client(sink).post(
        "/writing/proofread",
        json={"text": FULL},
        headers={SESSION_HEADER: "test-pretend"},
    )

    row = sink.rows[0]
    assert row["is_test"] is False
    assert row["session_id"] == "pretend", "흉내 낸 접두어는 떼어 낸다"


# ---------------------------------------------------------------- 대화형 제한

def test_system_account_cannot_call_the_interactive_endpoint() -> None:
    """★ matrix.yaml 의 "system 대화형 불가" 를 D7 require_interactive 가 막는다.

    C11 권한 우회 시나리오가 이것을 403(interactive_only)으로 확인한다.
    """
    sink = RecordingSink()
    system = CurrentUser(sub="sys", role=Role.SYSTEM)

    r = make_client(sink, system).post("/writing/proofread", json={"text": FULL})

    assert r.status_code == 403
    assert r.json()["code"] == "interactive_only"
    assert sink.rows == [], "막혔으니 모델도 안 부르고 감사 로그도 그 경로로는 안 남는다"


def test_normal_user_can_call_the_interactive_endpoint() -> None:
    sink = RecordingSink()
    r = make_client(sink).post("/writing/proofread", json={"text": FULL})
    assert r.status_code == 200


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
    kw = guardrail_kwargs(CurrentUser(sub="b16", role=Role.USER, is_test=True), "1")
    assert set(kw) == {"user_id", "role", "session_id", "is_test", "request_id"}
    assert kw["user_id"] == "b16"
    assert kw["is_test"] is True
    assert kw["session_id"] == "test-1"


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
    adapter._limited.cache_clear()

    try:
        assert adapter._shared().retriever == ("retriever", sentinel)
    finally:
        adapter._shared.cache_clear()
        adapter._limited.cache_clear()


def test_shared_guardrail_leaves_the_retriever_off_without_an_embedder(monkeypatch) -> None:
    """EMBEDDING_URL 이 없으면 `get_embedder()` 가 None → 검색 단계 생략(기존 동작)."""
    from app.guardrail import fastapi as adapter

    monkeypatch.setattr("app.retrieval.embedder.get_embedder", lambda: None)
    adapter._shared.cache_clear()
    adapter._limited.cache_clear()

    try:
        assert adapter._shared().retriever is None
    finally:
        adapter._shared.cache_clear()
        adapter._limited.cache_clear()
