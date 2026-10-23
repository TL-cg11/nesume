"""A13 조립·API — 모델이 못 하는 일(글자 수 세기)을 서버가 받아낸다."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import CurrentUser, Role, get_current_user
from app.features.style import service
from app.features.style.router import get_guardrail, router
from app.features.style.service import adjust, invented_numbers, verify_rewrite
from app.guardrail import Guardrail, LlmClient
from app.pii import InMemoryVaultStore
from tests.guardrail.fakes import FakeProvider

pytestmark = pytest.mark.anyio

#: 합니다체, 숫자 하나. 규칙으로 줄일 자리가 있다
LONG = (
    "저는 개인적으로 매우 많은 프로젝트를 담당하게 되었습니다.  "
    "그렇기 때문에 협업에 대하여 배웠고 응답시간을 40% 단축하였습니다."
)


def guard_with(reply: str = "", *, replies: list[str] | None = None):
    provider = FakeProvider(reply=reply)
    if replies is not None:
        provider = _Scripted(replies)
    return Guardrail(llm=LlmClient(provider=provider), vault=InMemoryVaultStore()), provider


class _Scripted(FakeProvider):
    """응답을 순서대로 돌려준다. 다시 요청하는 동작을 보려고 쓴다."""

    def __init__(self, replies: list[str]) -> None:
        super().__init__()
        self._replies = list(replies)

    async def generate(self, request, *, timeout_s):  # type: ignore[no-untyped-def]
        self.reply = self._replies.pop(0) if self._replies else ""
        return await super().generate(request, timeout_s=timeout_s)


# ---------------------------------------------------------------- 규칙만으로 끝나는 경우

async def test_no_model_call_when_rules_are_enough() -> None:
    """★ 규칙으로 제한과 문체를 맞췄으면 모델을 부를 이유가 없다."""
    guard, provider = guard_with()
    result = await adjust(LONG, guard=guard, user_id="u1", role="user", limit=200)

    assert provider.calls == []
    assert result.rule_only_fits is True
    assert result.counts["rule_savings"] > 0


async def test_rule_count_previews_the_result() -> None:
    result = await adjust(LONG, guard=Guardrail(), user_id="u1", role="user", limit=200)
    assert result.rule_count is not None
    assert result.rule_count.total == result.count.total - result.counts["rule_savings"]


async def test_mixed_tone_alone_triggers_a_rewrite() -> None:
    """길이는 맞아도 문체가 섞이면 고칠 거리가 있다."""
    guard, provider = guard_with(reply="강합니다. 해냈습니다.")
    result = await adjust(
        "강합니다. 해냈어요.", guard=guard, user_id="u1", role="user", limit=1000
    )
    assert len(provider.calls) == 1
    assert result.rewrite is not None


# ---------------------------------------------------------------- ★ 서버가 다시 센다

async def test_model_reply_over_the_limit_is_rejected() -> None:
    """★ 모델은 글자 수를 세지 못한다.

    맞지도 않는 글을 "줄였습니다" 로 내보내면 사용자는 **저장 단계에서 거절당한다.**
    """
    guard, _ = guard_with(reply="가" * 300)
    result = await adjust(LONG, guard=guard, user_id="u1", role="user", limit=50)

    assert result.rewrite is None
    assert result.rejected_reason is not None
    assert "넘습니다" in result.rejected_reason


async def test_asks_once_more_when_the_length_misses() -> None:
    """길이만 틀렸으면 한 번 더 요청한다. 상한은 MAX_REWRITE_ATTEMPTS."""
    guard, provider = guard_with(replies=["가" * 300, "짧게 줄였습니다."])
    result = await adjust(LONG, guard=guard, user_id="u1", role="user", limit=50)

    assert len(provider.calls) == 2
    assert result.attempts == 2
    assert result.rewrite is not None
    assert result.rewrite.count.total <= 50


async def test_attempts_are_capped() -> None:
    guard, provider = guard_with(reply="가" * 300)
    result = await adjust(LONG, guard=guard, user_id="u1", role="user", limit=50)

    assert len(provider.calls) == service.MAX_REWRITE_ATTEMPTS
    assert result.rewrite is None


# ---------------------------------------------------------------- ★ 지어낸 숫자

async def test_invented_number_discards_the_whole_rewrite() -> None:
    """★ 자소서에서 가장 위험한 환각은 성과 수치다.

    다시 쓰기는 글 전체가 바뀌므로 **일부만 믿을 수 없다.**
    """
    # 제한을 넘겨 놓아야 모델이 불린다 (규칙만으로 맞으면 부르지 않는다)
    guard, _ = guard_with(reply="응답시간을 60% 단축하고 비용 1,200만원을 절감했습니다.")
    result = await adjust(LONG, guard=guard, user_id="u1", role="user", limit=40)

    assert result.rewrite is None
    assert "원문에 없는 숫자" in (result.rejected_reason or "")


async def test_invented_number_does_not_trigger_a_retry() -> None:
    """다시 물어도 같은 사실을 또 만든다. 호출을 한 번으로 끝낸다."""
    guard, provider = guard_with(reply="60% 올렸습니다.")
    result = await adjust(LONG, guard=guard, user_id="u1", role="user", limit=40)

    assert len(provider.calls) == 1
    assert result.attempts == 1


def test_numbers_ignore_thousand_separators() -> None:
    assert invented_numbers("비용 1200만원", "비용 1,200만원") == set()


def test_keeping_the_same_numbers_passes() -> None:
    rewrite, reason = verify_rewrite(
        "응답시간을 40% 단축했습니다", "응답시간을 40% 줄였습니다",
        limit=100, target_tone="formal",
    )
    assert reason is None
    assert rewrite is not None


def test_preamble_is_stripped_before_measuring() -> None:
    """형식을 지키라고 적어도 "다음과 같이 줄였습니다:" 가 붙어 온다.

    그대로 세면 길이 검사에서 떨어지는데, 떨어진 이유가 **본문이 길어서가 아니다.**
    """
    rewrite, reason = verify_rewrite(
        "원래 글입니다", "다음과 같이 줄였습니다: 짧은 글입니다",
        limit=10, target_tone="formal",
    )
    assert reason is None, reason
    assert rewrite is not None
    assert rewrite.text == "짧은 글입니다"


def test_off_tone_rewrite_is_rejected() -> None:
    rewrite, reason = verify_rewrite(
        "강합니다", "강해요", limit=100, target_tone="formal"
    )
    assert rewrite is None
    assert "합니다체" in (reason or "")


# ---------------------------------------------------------------- ★ 모자란 분량

async def test_short_text_gets_questions_not_filler() -> None:
    """★ 분량을 모델에게 채우게 하면 없는 경험을 지어낸다 (A7·A11 과 같은 판단)."""
    guard, provider = guard_with(reply="아주 긴 글을 지어냅니다")
    result = await adjust(
        "짧습니다.", guard=guard, user_id="u1", role="user", limit=1000, min_chars=800
    )

    assert provider.calls == [], "모델을 부르지 않는다"
    assert result.questions == service.SHORT_QUESTIONS
    assert result.rewrite is None


# ---------------------------------------------------------------- 제공자 미정

async def test_rules_still_work_without_a_provider() -> None:
    result = await adjust(LONG, guard=Guardrail(), user_id="u1", role="user", limit=50)

    assert result.llm_unavailable is True
    assert result.trims, "규칙 제안은 그대로 나온다"


# ---------------------------------------------------------------- API

def make_client(reply: str = "", *, unconfigured: bool = False) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub="u1", role=Role.USER)
    if not unconfigured:
        guard, _ = guard_with(reply)
        app.dependency_overrides[get_guardrail] = lambda: guard
    return TestClient(app)


def test_adjust_endpoint() -> None:
    body = make_client().post(
        "/style/adjust", json={"text": LONG, "limit": 200}
    ).json()

    assert body["count"]["total"] == len(LONG)
    assert body["fits"] is True
    assert body["over_by"] == 0
    assert body["rule_only_fits"] is True
    assert body["trims"], "줄일 자리를 돌려준다"
    assert body["notice"]


def test_adjust_reports_tone_in_korean() -> None:
    body = make_client().post(
        "/style/adjust", json={"text": "강합니다. 해냈어요.", "limit": 1000, "use_llm": False}
    ).json()

    assert body["tone"]["is_mixed"] is True
    assert body["tone"]["main_name"] == "합니다체"
    assert [s["text"] for s in body["tone"]["off_tone"]] == ["해냈어요."]
    assert body["tone"]["off_tone"][0]["tone_name"] == "해요체"


def test_adjust_reports_over_by() -> None:
    body = make_client().post(
        "/style/adjust", json={"text": "가" * 100, "limit": 50, "use_llm": False}
    ).json()
    assert body["fits"] is False
    assert body["over_by"] == 50


def test_adjust_rejects_tokenized_text() -> None:
    """★ 저장된 본문을 보내면 글자 수가 틀어진다. 422 로 알린다."""
    r = make_client().post(
        "/style/adjust", json={"text": "연락처 [[PHONE_1]] 입니다", "limit": 100}
    )
    assert r.status_code == 422
    assert "토큰" in r.json()["detail"]


def test_adjust_rejects_bad_tone() -> None:
    r = make_client().post("/style/adjust", json={"text": "글", "target_tone": "친근체"})
    assert r.status_code == 422


def test_adjust_rejects_min_over_limit() -> None:
    r = make_client().post(
        "/style/adjust", json={"text": "글", "limit": 100, "min_chars": 200}
    )
    assert r.status_code == 422


def test_adjust_survives_unconfigured_provider() -> None:
    r = make_client(unconfigured=True).post(
        "/style/adjust", json={"text": LONG, "limit": 50}
    )
    assert r.status_code == 200
    assert r.json()["llm_unavailable"] is True


def test_apply_endpoint() -> None:
    client = make_client()
    found = client.post(
        "/style/adjust", json={"text": LONG, "limit": 200, "use_llm": False}
    ).json()

    body = client.post("/style/apply", json={
        "text": LONG,
        "trims": found["trims"],
        "accepted": [t["id"] for t in found["trims"]],
    }).json()

    assert body["applied"] == len(found["trims"])
    assert body["count"]["total"] == found["rule_count"]["total"]
    assert len(body["text"]) < len(LONG)


def test_apply_reports_stale_as_409() -> None:
    client = make_client()
    found = client.post(
        "/style/adjust", json={"text": LONG, "limit": 200, "use_llm": False}
    ).json()

    r = client.post("/style/apply", json={
        "text": "완전히 다른 글입니다",
        "trims": found["trims"],
        "accepted": [t["id"] for t in found["trims"]],
    })
    assert r.status_code == 409
