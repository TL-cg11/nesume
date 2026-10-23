"""A7 API 테스트.

★ DB 를 쓰지 않는다. A7 은 저장하지 않으므로 라우터만 올린 앱으로 검사한다.
  app.main 을 쓰면 다른 파트의 모델·DB 가 전부 딸려 온다.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import CurrentUser, Role, get_current_user, get_token_verifier
from app.features.writing import SEP
from app.features.writing.router import get_guardrail, router
from app.features.writing.schemas import MAX_TEXT_LEN
from app.guardrail import Guardrail, LlmClient
from app.pii import InMemoryVaultStore
from tests.guardrail.fakes import FakeProvider

FULL = ("2025년 교내 프로젝트에서 예약 지연 문제를 맡게 되었습니다. "
        "저는 최선을 다했습니다. 캐시를 도입할수있었고 구조가 개선되어집니다. "
        "그 결과 응답시간을 40% 단축했습니다.")


def make_client(reply: str = "", *, unconfigured: bool = False) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub="u1", role=Role.USER)
    if not unconfigured:
        app.dependency_overrides[get_guardrail] = lambda: Guardrail(
            llm=LlmClient(provider=FakeProvider(reply=reply)), vault=InMemoryVaultStore()
        )
    return TestClient(app)


# ---------------------------------------------------------------- proofread

def test_proofread_returns_suggestions() -> None:
    r = make_client().post("/writing/proofread", json={"text": FULL})
    assert r.status_code == 200

    body = r.json()
    rule_ids = {s["rule_id"] for s in body["suggestions"]}
    assert "WR_SPACING" in rule_ids
    assert "WR_DOUBLE_PASSIVE" in rule_ids
    assert body["star"]["count"] >= 3


def test_proofread_reports_star_in_korean() -> None:
    r = make_client().post("/writing/proofread", json={"text": "열심히 했습니다."})
    body = r.json()

    assert body["star"]["count"] == 0
    assert "상황(Situation)" in body["star"]["missing_names"], "화면에 그대로 보여줄 이름"
    assert body["llm_used"] is True, "요소 수로 2차를 막지 않는다 (2026-10-22 팀 회의)"
    star_ids = {s["rule_id"] for s in body["suggestions"] if s["kind"] == "star"}
    assert star_ids == {"WR_STAR_S", "WR_STAR_T", "WR_STAR_A", "WR_STAR_R"}


def test_proofread_without_llm() -> None:
    r = make_client().post("/writing/proofread", json={"text": FULL, "use_llm": False})
    assert r.json()["llm_used"] is False


def test_proofread_survives_unconfigured_provider() -> None:
    """★ 모델 제공자가 아직 미정이다. 그래도 1차 결과는 나와야 한다."""
    r = make_client(unconfigured=True).post("/writing/proofread", json={"text": FULL})

    assert r.status_code == 200
    body = r.json()
    assert body["llm_unavailable"] is True
    assert body["suggestions"], "규칙 제안은 그대로 나온다"


def test_proofread_includes_llm_suggestions() -> None:
    reply = f"최선을 다했습니다{SEP}병목 구간을 먼저 측정했습니다{SEP}구체적입니다"
    body = make_client(reply).post("/writing/proofread", json={"text": FULL}).json()

    assert body["llm_used"] is True
    assert any(s["source"] == "llm" for s in body["suggestions"])


def test_suggestion_shape() -> None:
    body = make_client().post("/writing/proofread", json={"text": FULL}).json()
    s = body["suggestions"][0]
    for key in ("id", "kind", "rule_id", "start", "end", "original",
                "suggested", "reason", "source", "confidence", "is_replacement"):
        assert key in s, key


# ---------------------------------------------------------------- 입력 검증

@pytest.mark.parametrize(
    "payload",
    [
        {"text": ""},
        {"text": "가" * (MAX_TEXT_LEN + 1)},
        {"text": "정상", "모르는키": 1},
        {},
    ],
)
def test_bad_request_is_rejected(payload: dict) -> None:
    assert make_client().post("/writing/proofread", json=payload).status_code == 422


def test_requires_authentication() -> None:
    """토큰 없이 부르면 401. 인증 의존성이 실제로 걸려 있는지 본다.

    토큰 검증기만 대체한다. 그러지 않으면 Cognito 설정이 없어
    RuntimeError(500)가 먼저 나서 인증 경로를 확인할 수 없다.
    """
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_token_verifier] = lambda: object()

    r = TestClient(app).post("/writing/proofread", json={"text": "글"})
    assert r.status_code == 401


# ---------------------------------------------------------------- apply

def _proofread_then(text: str, client: TestClient) -> list[dict]:
    return client.post("/writing/proofread", json={"text": text}).json()["suggestions"]


def test_apply_accepted_only() -> None:
    client = make_client()
    text = "캐시를 도입할수있었습니다."
    suggestions = _proofread_then(text, client)
    target = next(s for s in suggestions if s["rule_id"] == "WR_SPACING")

    r = client.post("/writing/apply", json={
        "text": text, "suggestions": suggestions, "accepted": [target["id"]],
    })
    assert r.status_code == 200
    assert r.json() == {"text": "캐시를 도입할 수 있었습니다.", "applied": 1}


def test_apply_nothing_returns_original() -> None:
    client = make_client()
    text = "캐시를 도입할수있었습니다."
    r = client.post("/writing/apply", json={
        "text": text, "suggestions": _proofread_then(text, client), "accepted": [],
    })
    assert r.json() == {"text": text, "applied": 0}


def test_apply_rejects_stale_text() -> None:
    """★ 제안을 받은 뒤 글을 고쳤으면 409. 그대로 반영하면 엉뚱한 자리가 덮어써진다."""
    client = make_client()
    text = "캐시를 도입할수있었습니다."
    suggestions = _proofread_then(text, client)
    target = next(s for s in suggestions if s["rule_id"] == "WR_SPACING")

    r = client.post("/writing/apply", json={
        "text": "앞에 문장을 더 쓴 뒤 " + text,   # 위치가 밀렸다
        "suggestions": suggestions,
        "accepted": [target["id"]],
    })
    assert r.status_code == 409


def test_apply_rejects_overlapping() -> None:
    client = make_client()
    text = "0123456789"
    a = {"id": "", "kind": "spacing", "rule_id": "R1", "start": 0, "end": 5,
         "original": "01234", "suggested": "X", "reason": "", "source": "rule",
         "confidence": "high", "is_replacement": True}
    b = dict(a, rule_id="R2", start=3, end=8, original="34567", suggested="Y")

    # id 는 서버가 내용으로 다시 계산하므로 요청의 id 값과 무관하게 맞춘다
    from app.features.writing.schemas import SuggestionOut
    a["id"] = SuggestionOut(**a).to_domain().id
    b["id"] = SuggestionOut(**b).to_domain().id

    r = client.post("/writing/apply", json={
        "text": text, "suggestions": [a, b], "accepted": [a["id"], b["id"]],
    })
    assert r.status_code == 400


def test_apply_ignores_guidance_only() -> None:
    client = make_client()
    text = "최선을 다했습니다."
    suggestions = _proofread_then(text, client)

    r = client.post("/writing/apply", json={
        "text": text, "suggestions": suggestions,
        "accepted": [s["id"] for s in suggestions],
    })
    assert r.json() == {"text": text, "applied": 0}
