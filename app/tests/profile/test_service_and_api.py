"""A14 조립·API — **본인만**이 지켜지는지 본다."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import CurrentUser, Role, get_current_user
from app.features.profile import (
    MIN_SOURCE_CHARS,
    InMemoryProfileStore,
    NotEnoughText,
    extract,
    prompt_fragment,
    service,
)
from app.features.profile.router import get_store, router
from app.models.writing_profile import MAX_TOP_TERMS
from tests.profile.test_extract import LONG_TEXT, filler

# ---------------------------------------------------------------- 조립

def test_build_stores_and_returns() -> None:
    store = InMemoryProfileStore()
    style = service.build(LONG_TEXT, owner_id="u1", store=store)

    assert store.get("u1") == style


def test_build_overwrites_instead_of_averaging() -> None:
    """★ 합치면 **어느 글이 반영됐는지 알 수 없다.** 사용자는 방금 쓴 글을 기준으로 본다."""
    store = InMemoryProfileStore()
    service.build(LONG_TEXT, owner_id="u1", store=store)
    second = service.build(filler(1200), owner_id="u1", store=store)

    assert store.get("u1") == second


def test_build_refuses_short_text_without_storing() -> None:
    store = InMemoryProfileStore()
    with pytest.raises(NotEnoughText):
        service.build("짧습니다.", owner_id="u1", store=store)
    assert store.get("u1") is None, "실패한 추출이 반쯤 저장되면 안 된다"


def test_delete_is_idempotent() -> None:
    store = InMemoryProfileStore()
    service.build(LONG_TEXT, owner_id="u1", store=store)

    assert service.delete("u1", store=store) is True
    assert service.delete("u1", store=store) is False
    assert store.get("u1") is None


def test_profiles_are_separated_by_owner() -> None:
    store = InMemoryProfileStore()
    service.build(LONG_TEXT, owner_id="u1", store=store)
    assert store.get("u2") is None


# ---------------------------------------------------------------- 프롬프트 문단

def test_prompt_fragment_says_not_to_change_facts_first() -> None:
    """★ 문체를 맞추라는 지시가 **사실을 바꾸는 허락**으로 읽히면 안 된다."""
    fragment = prompt_fragment(extract(LONG_TEXT))
    assert fragment.splitlines()[0].startswith("아래는 글쓴이의 평소 문체입니다")
    assert "내용과 사실은 그대로" in fragment


def test_prompt_fragment_is_empty_without_a_profile() -> None:
    """★ 모르는 것을 지시로 만들지 않는다.

    "문체 정보 없음" 같은 문구를 넣으면 모델이 그 문장에 반응한다
    (A5 `OutputContext` 를 비워 두면 그 검사만 건너뛰는 것과 같은 판단).
    """
    assert prompt_fragment(None) == ""


def test_prompt_fragment_carries_only_function_words() -> None:
    """프롬프트에 나가는 것도 화이트리스트 기능어뿐이다."""
    text = ("저는 가나다주식회사에서 홍길동 팀장과 일했습니다. " * 50)
    fragment = prompt_fragment(extract(text))

    assert "가나다주식회사" not in fragment
    assert "홍길동" not in fragment


def test_prompt_fragment_mentions_numbers_when_the_habit_is_there() -> None:
    fragment = prompt_fragment(extract(LONG_TEXT))
    assert "숫자" in fragment


def test_thin_sample_is_flagged() -> None:
    """1,000자를 넘겨도 문장이 적으면 표본은 얇다."""
    one_long_sentence = "가" * 1100 + "."
    assert service.is_thin(extract(one_long_sentence)) is True
    assert service.is_thin(extract(LONG_TEXT)) is False


def test_model_and_extractor_agree_on_how_many_terms_are_kept() -> None:
    """★ 모델 컬럼과 추출기 상한이 어긋나면 **저장할 때** 잘린다."""
    from app.features.profile.extract import TOP_N

    assert TOP_N == MAX_TOP_TERMS


# ---------------------------------------------------------------- API

def make_client(store: InMemoryProfileStore, *, role: Role = Role.USER, sub: str = "u1") -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub=sub, role=role)
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def test_put_then_get() -> None:
    store = InMemoryProfileStore()
    client = make_client(store)

    created = client.put("/profile/writing", json={"text": LONG_TEXT})
    assert created.status_code == 200
    body = created.json()
    assert "했습니다" in body["endings"]
    assert body["prompt_fragment"]
    assert body["thin"] is False
    assert body["notice"] is None

    assert client.get("/profile/writing").json() == body


def test_get_without_a_profile_says_what_is_needed() -> None:
    r = make_client(InMemoryProfileStore()).get("/profile/writing")

    assert r.status_code == 404
    assert str(MIN_SOURCE_CHARS) in r.json()["detail"]


def test_put_short_text_is_422_with_the_shortfall() -> None:
    r = make_client(InMemoryProfileStore()).put("/profile/writing", json={"text": "짧습니다."})

    assert r.status_code == 422
    assert "부족" in r.json()["detail"]


def test_put_tokenized_text_is_422() -> None:
    r = make_client(InMemoryProfileStore()).put(
        "/profile/writing", json={"text": filler(1100) + "[[PHONE_1]]"}
    )
    assert r.status_code == 422
    assert "토큰" in r.json()["detail"]


def test_delete_returns_204_even_when_absent() -> None:
    """지워 달라는 요청의 결과는 "없다" 이고, 그게 이미 참이면 성공이다."""
    client = make_client(InMemoryProfileStore())
    assert client.delete("/profile/writing").status_code == 204
    assert client.delete("/profile/writing").status_code == 204


def test_user_cannot_read_another_users_profile() -> None:
    """★ 저장소가 `owner_id` 로만 조회한다. 역할을 보고 통과시키는 분기가 없다."""
    store = InMemoryProfileStore()
    make_client(store, sub="u1").put("/profile/writing", json={"text": LONG_TEXT})

    other = make_client(store, sub="u2").get("/profile/writing")
    assert other.status_code == 404


@pytest.mark.parametrize("role", [Role.MENTOR, Role.OPERATOR])
def test_mentor_and_operator_cannot_read_someone_elses_profile(role: Role) -> None:
    """★ `tasks.md` A14 — **멘토·운영자 조회 불가.**

    말투 프로필은 **문체 지문**이라 공유된 자소서의 작성자를 역추적하는 데 쓸 수 있다.
    `matrix.yaml` 은 운영자에게 `personal: mask/all` 을 주지만, 이 값은
    **마스킹으로 가릴 수 있는 종류가 아니다.** 그래서 A14 는 그보다 엄격하다.
    """
    store = InMemoryProfileStore()
    make_client(store, sub="owner").put("/profile/writing", json={"text": LONG_TEXT})

    r = make_client(store, role=role, sub="someone-else").get("/profile/writing")
    assert r.status_code == 404, f"{role} 가 남의 프로필을 읽었습니다"


def test_response_never_carries_content_words() -> None:
    """응답에도 원문 조각이 없어야 한다 — 화면·로그로 바로 나가는 값이다."""
    store = InMemoryProfileStore()
    text = "저는 가나다주식회사에서 홍길동 팀장과 일했습니다. " * 50
    body = make_client(store).put("/profile/writing", json={"text": text}).json()

    dumped = str(body)
    assert "가나다주식회사" not in dumped
    assert "홍길동" not in dumped
