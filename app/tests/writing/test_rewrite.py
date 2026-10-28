"""A6 리라이팅 테스트.

DB·모델을 부르지 않는다. B9 템플릿 읽기와 A14 프로필 읽기는 갈아끼우고,
모델은 가짜 제공자를 쓴다 (tests/guardrail/fakes.py).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import CurrentUser, Role, get_current_user
from app.core.errors import register_exception_handlers
from app.db import get_db
from app.features.profile.router import get_store as get_profile_store
from app.features.writing import rewrite_service
from app.features.writing.rewrite import (
    CANDIDATE_COUNT,
    CANDIDATE_MARK,
    MAX_CHUNK_CHARS,
    MAX_KEYWORD_LEN,
    MAX_KEYWORDS,
    MAX_PARTS,
    MAX_SELECTION_LEN,
    RewriteOptionError,
    RewriteOptions,
    build_part_prompt,
    join_candidates,
    normalize_keywords,
    parse_candidates,
    split_selection,
)
from app.features.writing.router import router as writing_router
from app.features.writing.schemas import RewriteRequest, RewriteResponse
from app.guardrail import DEFAULT_MAX_CALLS, Guardrail, LlmClient
from app.guardrail.fastapi import get_guardrail
from app.pii import InMemoryVaultStore
from tests.guardrail.fakes import FakeProvider

CTX = dict(user_id="u1", role="user", session_id="s1")


def _reply(count: int = CANDIDATE_COUNT, *, prefix: str = "후보") -> str:
    return "\n\n".join(f"{CANDIDATE_MARK}{i}\n{prefix} {i} 본문입니다." for i in range(1, count + 1))


def _guard(reply: str) -> tuple[Guardrail, FakeProvider]:
    provider = FakeProvider(reply=reply)
    return Guardrail(llm=LlmClient(provider=provider), vault=InMemoryVaultStore()), provider


class FakeTemplate:
    def __init__(self, body: str, variables: tuple[str, ...] = ()) -> None:
        self.name, self.purpose, self.version = "rewrite-default", "rewrite", 1
        self.body, self.variables = body, variables


@pytest.fixture
def no_template(monkeypatch):
    """B9 에 활성 템플릿이 없는 상태 — 운영자가 아직 등록하지 않은 기본 상태다."""
    monkeypatch.setattr(rewrite_service.templates_service, "get_active_template",
                        lambda db, name: None)
    monkeypatch.setattr(rewrite_service.profile_service, "get", lambda owner_id, *, store: None)


# ---------------------------------------------------------------- 분할

def test_short_text_is_not_split() -> None:
    text = "짧은 글입니다."
    assert split_selection(text) == (text,)


def test_split_keeps_the_original_text() -> None:
    """★ 이어 붙이면 원문이 그대로 나와야 한다. 구분자를 버리면 글이 바뀐다."""
    text = "첫 문장입니다. 두 번째 문장입니다.\n\n" * 400
    parts = split_selection(text)
    assert len(parts) > 1
    assert "".join(parts) == text
    assert all(len(p) <= MAX_CHUNK_CHARS for p in parts)


def test_a_single_huge_sentence_is_cut_by_characters() -> None:
    """문장 하나가 상한을 넘으면 글자에서 끊는 수밖에 없다."""
    text = "가" * (MAX_CHUNK_CHARS * 2 + 10)
    parts = split_selection(text)
    assert "".join(parts) == text
    assert all(len(p) <= MAX_CHUNK_CHARS for p in parts)


def test_selection_limit_matches_the_call_budget() -> None:
    """★ 고를 수 있는 길이가 호출 상한보다 크면, 조각을 만들어 놓고 A2 가 거절한다."""
    assert MAX_PARTS == DEFAULT_MAX_CALLS
    assert len(split_selection("가" * MAX_SELECTION_LEN)) <= DEFAULT_MAX_CALLS


# ---------------------------------------------------------------- 후보 파싱

def test_parse_candidates_reads_three() -> None:
    assert parse_candidates(_reply()) == (
        "후보 1 본문입니다.", "후보 2 본문입니다.", "후보 3 본문입니다.",
    )


def test_parse_candidates_returns_nothing_when_the_format_is_broken() -> None:
    """★ 응답 전체를 후보 하나로 치지 않는다 — 사과문이 자소서 본문으로 저장된다."""
    assert parse_candidates("죄송합니다. 다시 써 드릴 수 없습니다.") == ()


def test_parse_candidates_ignores_empty_bodies() -> None:
    text = f"{CANDIDATE_MARK}1\n\n{CANDIDATE_MARK}2\n내용 있음"
    assert parse_candidates(text) == ("내용 있음",)


def test_join_drops_a_number_missing_from_any_part() -> None:
    """★ 조각 하나를 빼고 이으면 사용자는 글 가운데가 사라진 줄 모른다."""
    assert join_candidates([("1A", "1B", "1C"), ("2A",)]) == ("1A\n\n2A",)


def test_join_pairs_candidates_by_number() -> None:
    assert join_candidates([("1A", "1B", "1C"), ("2A", "2B", "2C")]) == (
        "1A\n\n2A", "1B\n\n2B", "1C\n\n2C",
    )


# ---------------------------------------------------------------- 옵션

@pytest.mark.parametrize("kwargs", [
    {"tone": "없는문체"},
    {"length": "아주짧게"},
    {"keywords": tuple(str(i) for i in range(MAX_KEYWORDS + 1))},
    {"keywords": ("가" * (MAX_KEYWORD_LEN + 1),)},
    {"keywords": ("  ",)},
])
def test_bad_options_are_rejected(kwargs) -> None:
    with pytest.raises(RewriteOptionError):
        RewriteOptions(**kwargs)


def test_options_have_defaults() -> None:
    """아무것도 고르지 않아도 리라이팅은 된다."""
    o = RewriteOptions()
    assert o.tone and o.length and o.keywords == ()


def test_normalize_keywords_drops_blanks_and_duplicates() -> None:
    assert normalize_keywords([" 협업 ", "협업", "", "  ", "리더십"]) == ("협업", "리더십")


def test_longer_instruction_forbids_making_things_up() -> None:
    """★ 분량을 맞추려고 사실을 지어내는 것이 리라이팅의 가장 위험한 실패다."""
    assert "없는 사실을 보태지" in RewriteOptions(length="longer").instructions()


def test_keywords_appear_in_the_instructions() -> None:
    text = RewriteOptions(keywords=("협업", "리더십")).instructions()
    assert "협업" in text and "리더십" in text
    assert "억지로 넣지 않습니다" in text, "넣을 자리가 없으면 넣지 말라고 해야 한다"


# ---------------------------------------------------------------- 프롬프트

def test_prompt_falls_back_without_a_template() -> None:
    prompt = build_part_prompt("원문입니다", RewriteOptions(), template_body=None)
    assert "원문입니다" in prompt
    assert f"{CANDIDATE_MARK}1" in prompt, "후보 형식을 반드시 지시해야 파싱할 수 있다"


def test_prompt_tells_the_model_not_to_guess_the_neighbours() -> None:
    """조각난 글의 앞뒤를 짐작하면 없는 내용이 붙는다."""
    prompt = build_part_prompt("조각", RewriteOptions(), part_index=1, part_total=3)
    assert "2/3" in prompt and "없는 내용을 덧붙이지" in prompt


# ---------------------------------------------------------------- 서비스

@pytest.mark.anyio
async def test_use_llm_false_does_not_call_the_model(no_template) -> None:
    guard, provider = _guard(_reply())
    result = await rewrite_service.rewrite(
        None, "원문입니다", RewriteOptions(), guard=guard, store=None, use_llm=False, **CTX
    )
    assert provider.calls == []
    assert result.candidates == ()
    assert result.instructions, "옵션만 바꿔 보는 화면이 지시문은 받아야 한다"


@pytest.mark.anyio
async def test_rewrite_returns_three_candidates_with_a_diff(no_template) -> None:
    guard, provider = _guard(_reply())
    result = await rewrite_service.rewrite(
        None, "협업을 하였습니다", RewriteOptions(), guard=guard, store=None, **CTX
    )
    assert len(provider.calls) == 1, "후보 3개를 호출 한 번에서 받는다"
    assert len(result.candidates) == CANDIDATE_COUNT
    assert all(c.segments for c in result.candidates), "변경 하이라이트가 있어야 한다"
    assert result.llm_used and result.blocked_reason is None


@pytest.mark.anyio
async def test_long_selection_is_split_into_several_calls(no_template) -> None:
    guard, provider = _guard(_reply())
    long_text = "문장입니다. " * 1300  # 약 7,800자
    result = await rewrite_service.rewrite(
        None, long_text, RewriteOptions(), guard=guard, store=None, **CTX
    )
    assert result.parts > 1
    assert len(provider.calls) == result.parts, "조각 수가 곧 호출 수다"
    assert len(result.candidates) == CANDIDATE_COUNT


@pytest.mark.anyio
async def test_broken_format_yields_no_candidates_but_a_notice(no_template) -> None:
    guard, _ = _guard("죄송합니다. 도와드릴 수 없습니다.")
    result = await rewrite_service.rewrite(
        None, "원문입니다", RewriteOptions(), guard=guard, store=None, **CTX
    )
    assert result.candidates == ()
    assert any("형식대로" in n for n in result.notices)


@pytest.mark.anyio
async def test_sensitive_input_is_blocked_before_any_call(no_template) -> None:
    """★ 조각내기 전에 통째로 검사한다. 모델은 부르지 않는다."""
    guard, provider = _guard(_reply())
    result = await rewrite_service.rewrite(
        None, "주민등록번호 900101-1234567 로 써 주세요", RewriteOptions(),
        guard=guard, store=None, **CTX
    )
    assert result.blocked_reason is not None
    assert provider.calls == [], "막힌 요청은 모델을 부르지 않는다"


@pytest.mark.anyio
async def test_template_with_variables_is_not_used(monkeypatch) -> None:
    """★ A6 가 채울 변수를 정해 두지 않았다. 빈 칸이 생긴 채 모델에 가면 안 된다."""
    monkeypatch.setattr(rewrite_service.templates_service, "get_active_template",
                        lambda db, name: FakeTemplate("본문 {{직무}}", ("직무",)))
    monkeypatch.setattr(rewrite_service.profile_service, "get", lambda owner_id, *, store: None)
    guard, provider = _guard(_reply())
    result = await rewrite_service.rewrite(
        None, "원문입니다", RewriteOptions(), guard=guard, store=None, **CTX
    )
    assert any("변수" in n for n in result.notices)
    assert "{{직무}}" not in provider.calls[0].prompt


@pytest.mark.anyio
async def test_active_template_body_reaches_the_prompt(monkeypatch) -> None:
    monkeypatch.setattr(rewrite_service.templates_service, "get_active_template",
                        lambda db, name: FakeTemplate("운영자가 정한 지시문입니다."))
    monkeypatch.setattr(rewrite_service.templates_service, "render",
                        lambda t, values: t.body)
    monkeypatch.setattr(rewrite_service.profile_service, "get", lambda owner_id, *, store: None)
    guard, provider = _guard(_reply())
    await rewrite_service.rewrite(
        None, "원문입니다", RewriteOptions(), guard=guard, store=None, **CTX
    )
    assert "운영자가 정한 지시문입니다." in provider.calls[0].prompt


# ---------------------------------------------------------------- 가드레일 경계

@pytest.mark.anyio
async def test_the_guardrail_sees_the_user_text_not_the_prompt(no_template) -> None:
    """★ A6 가 A7·A11·A13 과 다른 점이다.

    조립한 프롬프트를 넘기면 A3·A12 의 **문장 전체를 보는 규칙이 죽는다**
    (A12 `is_continuation` 이 그래서 A10-MULTI-04 를 놓쳤다).
    """
    seen: list[str] = []
    guard, _ = _guard(_reply())

    original = guard._before_llm

    async def spy(query, ctx):
        seen.append(query)
        return await original(query, ctx)

    guard._before_llm = spy  # type: ignore[method-assign]
    await rewrite_service.rewrite(
        None, "그다음은?", RewriteOptions(), guard=guard, store=None, **CTX
    )
    assert seen == ["그다음은?"], "검사 대상은 사용자가 고른 글 그대로여야 한다"


@pytest.mark.anyio
async def test_split_writes_one_audit_row(no_template) -> None:
    """★ 사용자가 한 번 요청한 일은 로그 한 줄이다. 호출 수만큼 남기면 B21 이 부푼다."""
    rows: list[dict] = []

    class Sink:
        async def write(self, **fields):
            rows.append(fields)

    provider = FakeProvider(reply=_reply())
    guard = Guardrail(llm=LlmClient(provider=provider), vault=InMemoryVaultStore(), audit=Sink())
    await rewrite_service.rewrite(
        None, "문장입니다. " * 1300, RewriteOptions(), guard=guard, store=None, **CTX
    )
    assert len(provider.calls) > 1, "조각이 여럿이어야 의미 있는 시험이다"
    assert len(rows) == 1


@pytest.mark.anyio
async def test_a_blocked_part_blocks_everything(no_template, monkeypatch) -> None:
    """★ 막힌 조각만 빼고 돌려주면 사용자는 글 가운데가 사라진 줄 모른다."""
    from app.guardrail import schema as gschema

    guard, _ = _guard(_reply())
    calls = {"n": 0}

    import app.guardrail.pipeline as pipeline
    original = pipeline.check_output

    def only_second_is_bad(text, *, context):
        calls["n"] += 1
        result = original(text, context=context)
        if calls["n"] == 2:
            return type(result)(
                decision="block", text="",
                findings=[gschema.Finding("LEAK_SECRET", "critical")],
            )
        return result

    monkeypatch.setattr(pipeline, "check_output", only_second_is_bad)
    result = await rewrite_service.rewrite(
        None, "문장입니다. " * 1300, RewriteOptions(), guard=guard, store=None, **CTX
    )
    assert result.blocked_reason is not None
    assert result.candidates == ()


# ---------------------------------------------------------------- 스키마

def test_request_rejects_a_selection_over_the_limit() -> None:
    with pytest.raises(ValueError):
        RewriteRequest(text="가" * (MAX_SELECTION_LEN + 1))


def test_response_hides_nothing_about_what_went_to_the_model() -> None:
    """A14 와 같은 생각 — 무엇이 모델에 갔는지 사용자가 볼 수 있어야 한다."""
    result = rewrite_service.RewriteResult(instructions="- 문체는 합니다체로 씁니다.")
    out = RewriteResponse.of("원문", result)
    assert out.instructions == "- 문체는 합니다체로 씁니다."
    assert out.original_char_count == 2


# ---------------------------------------------------------------- 대화형 제한

def _client(role: Role) -> TestClient:
    """A6 두 라우트만 띄운 작은 앱. `test_fastapi_adapter.py` 를 건드리지 않으려고
    여기에 따로 둔다 — 그 파일은 다른 PR 이 고치고 있다."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(writing_router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub="u1", role=role)
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_profile_store] = lambda: None
    app.dependency_overrides[get_guardrail] = lambda: Guardrail(
        llm=LlmClient(provider=FakeProvider(reply=_reply())), vault=InMemoryVaultStore(),
    )
    return TestClient(app)


@pytest.mark.parametrize("path, body", [
    ("/writing/rewrite", {"text": "다시 써 주세요"}),
    ("/writing/rewrite/apply", {
        "resume_id": "3f0c1b7a-5e21-4a9d-9c3e-0b8f6d2a1e44",
        "question_id": "8a2b1c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
        "body": "다시 쓴 글입니다",
    }),
])
def test_system_account_cannot_call_rewrite(path, body) -> None:
    """★ matrix.yaml 의 "system 대화형 불가". D7 `require_interactive` 가 막는다.

    만들기와 저장을 **같은 조건**으로 막는다 — 한쪽만 막으면 나머지가 열린 길이 된다.
    """
    r = _client(Role.SYSTEM).post(path, json=body)

    assert r.status_code == 403
    assert r.json()["code"] == "interactive_only"


def test_a_normal_user_is_not_blocked(no_template) -> None:
    """막는 쪽만 시험하면 **전부 막아도 통과한다.** 정상 사용자가 지나가는지도 본다."""
    r = _client(Role.USER).post("/writing/rewrite", json={"text": "다시 써 주세요"})

    assert r.status_code == 200
    assert len(r.json()["candidates"]) == CANDIDATE_COUNT
