"""PII 모듈 단위 테스트.

DB도 네트워크도 쓰지 않는다. 치환표는 InMemoryVaultStore 로 대체한다.
"""

from __future__ import annotations

import pytest

from app.pii import (
    NO_EXPIRY,
    InMemoryVaultStore,
    VaultExpired,
    VaultOwnerMismatch,
    detect,
    detokenize,
    detokenize_fields,
    fix_korean_particles,
    mask,
    tokenize,
    tokenize_fields,
    validate_input,
)
from tests.pii.cases import (
    KNOWN_MISSES,
    MUST_DETECT,
    MUST_NOT_DETECT,
    PARTICLE_CASES,
    ROUNDTRIP,
)


# ---------------------------------------------------------------- detect

@pytest.mark.parametrize("text,expected", MUST_DETECT)
def test_detects_expected_kinds(text: str, expected: set[str]) -> None:
    found = {hit.kind for hit in detect(text)}
    assert expected <= found, f"놓친 종류: {expected - found}"


@pytest.mark.parametrize("text", MUST_NOT_DETECT)
def test_no_false_positives(text: str) -> None:
    hits = detect(text)
    assert hits == [], f"오탐: {[(h.kind, text[h.start:h.end]) for h in hits]}"


@pytest.mark.parametrize("text,expected,reason", KNOWN_MISSES)
@pytest.mark.xfail(reason="1차 프로젝트에서도 미탐이었던 항목. 잡게 되면 표시를 뗀다", strict=False)
def test_known_misses(text: str, expected: set[str], reason: str) -> None:
    found = {hit.kind for hit in detect(text)}
    assert expected <= found, reason


def test_hit_never_carries_raw_value() -> None:
    """Hit 에 원문이 들어가지 않는다. 로그로 새어나갈 수 있는 구조체다."""
    hits = detect("연락처 010-1234-5678")
    assert hits
    for hit in hits:
        for field_value in vars(hit).values():
            assert "1234" not in str(field_value), "Hit 에 원문 조각이 들어갔다"


def test_rrn_wins_over_phone() -> None:
    """1차에서 났던 버그 — PHONE 규칙이 주민번호를 먼저 가로채면 안 된다."""
    hits = detect("9001011234567")
    assert [h.kind for h in hits] == ["RRN"]


def test_empty_text() -> None:
    assert detect("") == []
    assert mask("") == ""
    assert validate_input("").ok is True


# ---------------------------------------------------------------- validate_input

def test_rejects_rrn() -> None:
    result = validate_input("주민번호는 900101-1234567 입니다")
    assert result.ok is False
    assert {b.kind for b in result.blocked} == {"RRN"}


def test_allows_normal_text() -> None:
    assert validate_input("저는 백엔드 개발자로 지원합니다").ok is True


def test_blocked_reason_has_no_raw_value() -> None:
    """거절 사유에 입력값을 되비추지 않는다. 되비추면 화면과 로그에 또 남는다."""
    result = validate_input("주민번호 900101-1234567")
    assert "900101" not in repr(result)


# ---------------------------------------------------------------- mask

def test_mask_hides_everything_by_default() -> None:
    """★ 기본값은 전부 가린다.

    1차에서는 대조용으로 뒷자리 4자리를 남겼다. 2차에서는 감사 로그에
    query_hash(원문 SHA-256)가 따로 있어 대조를 해시가 맡는다. 뒷자리를 남기면
    이득 없이 PII 만 남는다 (spec 15장 "감사 로그에 PII 유입").
    """
    masked = mask("연락처 010-1234-5678")
    assert not any(ch.isdigit() for ch in masked), f"숫자가 남았다: {masked}"


def test_mask_keep_tail_is_opt_in() -> None:
    """대조용 꼬리가 꼭 필요한 호출자는 명시한다."""
    assert "5678" in mask("연락처 010-1234-5678", keep_tail=4)


def test_mask_hides_email_domain_by_default() -> None:
    """개인 메일 도메인은 소속을 드러낸다."""
    masked = mask("메일은 hong@example.com 입니다")
    assert "example.com" not in masked
    assert "hong" not in masked


def test_mask_hides_rrn_completely() -> None:
    """거절 대상은 뒷자리도 남기지 않는다."""
    masked = mask("900101-1234567")
    assert not any(ch.isdigit() for ch in masked)


def test_mask_keeps_surrounding_text() -> None:
    masked = mask("연락처는 010-1234-5678 입니다")
    assert masked.startswith("연락처는")
    assert masked.endswith("입니다")


# ---------------------------------------------------------------- tokenize / detokenize

@pytest.mark.anyio
@pytest.mark.parametrize("text,expected_tokens", ROUNDTRIP)
async def test_roundtrip(text: str, expected_tokens: int) -> None:
    store = InMemoryVaultStore()
    t = await tokenize(text, owner_id="u1", store=store)

    assert len(set(h.token for h in t.hits if h.token)) == expected_tokens
    d = await detokenize(t.text, t.vault_id, "u1", store=store, fix_particles=False)
    assert d.text == text
    assert d.unresolved == []


@pytest.mark.anyio
async def test_same_value_gets_same_token() -> None:
    """한 문서에서 같은 값은 같은 토큰. 다른 토큰을 주면 모델이 다른 사람으로 읽는다."""
    store = InMemoryVaultStore()
    t = await tokenize("이름: 김철수 그리고 이름: 김철수", owner_id="u1", store=store)
    tokens = {h.token for h in t.hits}
    assert len(tokens) == 1


@pytest.mark.anyio
async def test_tokenized_text_has_no_raw_pii() -> None:
    store = InMemoryVaultStore()
    t = await tokenize("이름: 김철수, 연락처 010-1234-5678", owner_id="u1", store=store)
    assert "김철수" not in t.text
    assert "010-1234-5678" not in t.text


@pytest.mark.anyio
async def test_owner_mismatch_raises() -> None:
    """vault_id 만으로 열리면 그 값이 유출됐을 때 남의 원문이 복원된다."""
    store = InMemoryVaultStore()
    t = await tokenize("이름: 김철수", owner_id="u1", store=store)
    with pytest.raises(VaultOwnerMismatch):
        await detokenize(t.text, t.vault_id, "u2", store=store)


@pytest.mark.anyio
async def test_missing_vault_raises() -> None:
    store = InMemoryVaultStore()
    with pytest.raises(VaultExpired):
        await detokenize("[[PERSON_1]]", "없는-id", "u1", store=store)


@pytest.mark.anyio
async def test_unresolved_token_is_reported() -> None:
    """치환표에 없는 토큰은 조용히 넘기지 않고 unresolved 로 알린다."""
    store = InMemoryVaultStore()
    t = await tokenize("이름: 김철수", owner_id="u1", store=store)
    d = await detokenize(t.text + " [[PERSON_9]]", t.vault_id, "u1", store=store)
    assert d.unresolved == ["[[PERSON_9]]"]


@pytest.mark.anyio
async def test_vault_repr_hides_entries() -> None:
    """치환표가 스택트레이스·로그로 새어나가지 않는다."""
    store = InMemoryVaultStore()
    t = await tokenize("이름: 김철수", owner_id="u1", store=store)
    vault = await store.load(t.vault_id)
    assert vault is not None
    assert "김철수" not in repr(vault)


# ---------------------------------------------------------------- 조사 보정

@pytest.mark.parametrize("text,expected", PARTICLE_CASES)
def test_particle_correction(text: str, expected: str) -> None:
    assert fix_korean_particles(text) == expected


@pytest.mark.anyio
async def test_detokenize_fixes_particles() -> None:
    """모델이 토큰 뒤에 붙인 조사를 복원된 단어에 맞게 고친다."""
    store = InMemoryVaultStore()
    t = await tokenize("이름: 김철수", owner_id="u1", store=store)
    token = t.hits[0].token
    # 모델이 받침 있는 단어로 보고 "은"을 붙인 상황
    llm_output = f"{token}은 지원했습니다"
    d = await detokenize(llm_output, t.vault_id, "u1", store=store)
    assert d.text == "김철수는 지원했습니다"


@pytest.mark.anyio
async def test_detokenize_fixes_only_particles_right_after_tokens() -> None:
    """토큰과 무관한 낱말은 건드리지 않는다. 전에는 "있는"·"먹는" 이 "있은"·"먹은" 이 됐다(11/3)."""
    store = InMemoryVaultStore()
    t = await tokenize("이름: 김철수 / 이름: 김동현", owner_id="u1", store=store)
    a, b = (h.token for h in t.hits)
    llm_output = f"{a}은 진로 상담 경험이 있는 지원자, {b}는 먹는 일에 진심, {a}로 정했다, {b}와 함께"
    d = await detokenize(llm_output, t.vault_id, "u1", store=store)
    assert d.text == "김철수는 진로 상담 경험이 있는 지원자, 김동현은 먹는 일에 진심, 김철수로 정했다, 김동현과 함께"


@pytest.mark.anyio
async def test_detokenize_leaves_particle_after_non_hangul_value() -> None:
    """숫자·영문으로 끝나는 값(전화번호·이메일) 뒤 조사는 모델이 쓴 대로 둔다."""
    store = InMemoryVaultStore()
    t = await tokenize("메일 hong@example.com", owner_id="u1", store=store)
    d = await detokenize(f"{t.hits[0].token}로 연락하세요", t.vault_id, "u1", store=store)
    assert d.text == "hong@example.com로 연락하세요"


# ---------------------------------------------------------------- 만료 없는 치환표 (B7)

@pytest.mark.anyio
async def test_no_expiry_vault_never_expires() -> None:
    """저장용 치환표. 30분 뒤 지우면 그 자소서는 영구히 복원 불가가 된다."""
    store = InMemoryVaultStore()
    t = await tokenize("이름: 김철수", owner_id="u1", store=store, ttl_seconds=NO_EXPIRY)

    vault = await store.load(t.vault_id)
    assert vault is not None
    assert vault.expires_at is None
    assert vault.is_permanent is True
    # 아무리 먼 미래를 줘도 만료되지 않는다
    assert vault.is_expired(now=1e18) is False


@pytest.mark.anyio
async def test_no_expiry_vault_still_restores_later() -> None:
    store = InMemoryVaultStore()
    t = await tokenize("연락처 010-1234-5678", owner_id="u1", store=store, ttl_seconds=None)
    d = await detokenize(t.text, t.vault_id, "u1", store=store, fix_particles=False)
    assert d.text == "연락처 010-1234-5678"


@pytest.mark.anyio
async def test_ttl_vault_expires() -> None:
    """임시 치환표는 그대로 만료된다. 오래 남을수록 유출 창이 넓어진다."""
    store = InMemoryVaultStore()
    t = await tokenize("이름: 김철수", owner_id="u1", store=store, ttl_seconds=0)

    assert await store.load(t.vault_id) is None, "만료된 치환표가 조회됐다"
    with pytest.raises(VaultExpired):
        await detokenize(t.text, t.vault_id, "u1", store=store)


@pytest.mark.anyio
async def test_default_ttl_is_not_permanent() -> None:
    """기본값은 임시다. 저장용은 호출자가 명시해야 한다."""
    store = InMemoryVaultStore()
    t = await tokenize("이름: 김철수", owner_id="u1", store=store)
    vault = await store.load(t.vault_id)
    assert vault is not None and vault.is_permanent is False


# ---------------------------------------------------------------- 필드 묶음 (B4·B5)

@pytest.mark.anyio
async def test_fields_share_one_vault() -> None:
    """문항마다 치환표를 따로 만들면 문항 수만큼 생긴다."""
    store = InMemoryVaultStore()
    r = await tokenize_fields(
        {"q1": "이름: 김철수 입니다", "q2": "연락처 010-1234-5678"},
        owner_id="u1",
        store=store,
    )

    assert set(r.texts) == {"q1", "q2"}
    assert "김철수" not in r.texts["q1"]
    assert "010-1234-5678" not in r.texts["q2"]
    assert len(store._items) == 1, "치환표는 하나여야 한다"


@pytest.mark.anyio
async def test_same_value_across_fields_gets_same_token() -> None:
    """★ 이것이 필드를 묶는 이유다. 다른 토큰을 주면 모델이 다른 사람으로 읽는다."""
    store = InMemoryVaultStore()
    r = await tokenize_fields(
        {"q1": "연락처 010-1234-5678", "q2": "다시 적습니다 010-1234-5678"},
        owner_id="u1",
        store=store,
    )

    tokens = {h.token for hits in r.hits.values() for h in hits}
    assert len(tokens) == 1, f"같은 값이 다른 토큰을 받았다: {tokens}"
    assert r.counts["PHONE"] == 2  # 두 번 나온 것은 그대로 센다


@pytest.mark.anyio
async def test_field_numbering_continues_across_fields() -> None:
    """번호는 문서 안에서 1부터 이어진다. 필드마다 1로 돌아가지 않는다."""
    store = InMemoryVaultStore()
    r = await tokenize_fields(
        {"q1": "이름: 김철수", "q2": "이름: 이영희"},
        owner_id="u1",
        store=store,
    )

    assert "[[PERSON_1]]" in r.texts["q1"]
    assert "[[PERSON_2]]" in r.texts["q2"]


@pytest.mark.anyio
async def test_fields_roundtrip() -> None:
    store = InMemoryVaultStore()
    original = {"q1": "이름: 김철수 입니다", "q2": "연락처 010-1234-5678", "q3": "개인정보 없음"}

    r = await tokenize_fields(original, owner_id="u1", store=store)
    d = await detokenize_fields(r.texts, r.vault_id, "u1", store=store, fix_particles=False)

    assert d.texts == original
    assert d.unresolved == {}


@pytest.mark.anyio
async def test_fields_detokenize_checks_owner() -> None:
    store = InMemoryVaultStore()
    r = await tokenize_fields({"q1": "이름: 김철수"}, owner_id="u1", store=store)
    with pytest.raises(VaultOwnerMismatch):
        await detokenize_fields(r.texts, r.vault_id, "u2", store=store)


@pytest.mark.anyio
async def test_fields_report_unresolved_per_field() -> None:
    store = InMemoryVaultStore()
    r = await tokenize_fields({"q1": "이름: 김철수", "q2": "정상"}, owner_id="u1", store=store)

    broken = dict(r.texts)
    broken["q2"] = "없는 토큰 [[PERSON_9]]"
    d = await detokenize_fields(broken, r.vault_id, "u1", store=store)

    assert d.unresolved == {"q2": ["[[PERSON_9]]"]}, "미복원 필드만 보고해야 한다"


@pytest.mark.anyio
async def test_empty_fields() -> None:
    store = InMemoryVaultStore()
    r = await tokenize_fields({}, owner_id="u1", store=store)
    assert r.texts == {}
    assert r.counts == {}


@pytest.mark.anyio
async def test_fields_can_be_permanent() -> None:
    """B4 자소서 저장 경로 — 묶음 + 만료 없음을 함께 쓴다."""
    store = InMemoryVaultStore()
    r = await tokenize_fields(
        {"q1": "이름: 김철수", "q2": "연락처 010-1234-5678"},
        owner_id="u1",
        store=store,
        ttl_seconds=NO_EXPIRY,
    )
    vault = await store.load(r.vault_id)
    assert vault is not None and vault.is_permanent is True


# ---------------------------------------------------------------- 배열 필드 (B5 경험 데이터)

@pytest.mark.anyio
async def test_list_field_keeps_shape() -> None:
    """태그·사용 기술은 배열이다. 배열로 받아 배열로 돌려준다."""
    store = InMemoryVaultStore()
    r = await tokenize_fields(
        {
            "제목": "이름: 김철수 의 프로젝트",
            "태그": ["연락처 010-1234-5678", "백엔드", "메일 hong@example.com"],
        },
        owner_id="u1",
        store=store,
    )

    assert isinstance(r.texts["제목"], str)
    assert isinstance(r.texts["태그"], list)
    assert len(r.texts["태그"]) == 3
    assert r.texts["태그"][1] == "백엔드", "PII 없는 원소는 그대로"
    assert "010-1234-5678" not in r.texts["태그"][0]


@pytest.mark.anyio
async def test_list_field_hits_are_indexed() -> None:
    """Hit 의 start/end 는 텍스트 하나 안의 위치다. 배열은 원소별 키로 나눈다."""
    store = InMemoryVaultStore()
    r = await tokenize_fields(
        {"태그": ["연락처 010-1234-5678", "백엔드"]}, owner_id="u1", store=store
    )

    assert set(r.hits) == {"태그[0]", "태그[1]"}
    assert len(r.hits["태그[0]"]) == 1
    assert r.hits["태그[1]"] == []


@pytest.mark.anyio
async def test_same_value_shared_between_str_and_list_fields() -> None:
    """★ 문자열 필드와 배열 원소에 같은 값이 있으면 같은 토큰을 받아야 한다."""
    store = InMemoryVaultStore()
    r = await tokenize_fields(
        {"상세": "연락처는 010-1234-5678 입니다", "태그": ["010-1234-5678"]},
        owner_id="u1",
        store=store,
    )

    all_tokens = {h.token for hits in r.hits.values() for h in hits}
    assert len(all_tokens) == 1, f"같은 값이 다른 토큰을 받았다: {all_tokens}"


@pytest.mark.anyio
async def test_list_field_roundtrip() -> None:
    store = InMemoryVaultStore()
    original = {
        "제목": "이름: 김철수 의 프로젝트",
        "성과": "연락처 010-1234-5678 로 문의",
        "태그": ["hong@example.com", "백엔드", ""],
        "사용기술": ["Python 3.12", "FastAPI"],
    }

    r = await tokenize_fields(original, owner_id="u1", store=store, ttl_seconds=NO_EXPIRY)
    d = await detokenize_fields(r.texts, r.vault_id, "u1", store=store, fix_particles=False)

    assert d.texts == original
    assert d.unresolved == {}


@pytest.mark.anyio
async def test_list_field_unresolved_is_indexed() -> None:
    store = InMemoryVaultStore()
    r = await tokenize_fields({"태그": ["이름: 김철수", "정상"]}, owner_id="u1", store=store)

    broken = {"태그": [r.texts["태그"][0], "없는 토큰 [[PERSON_9]]"]}
    d = await detokenize_fields(broken, r.vault_id, "u1", store=store)

    assert d.unresolved == {"태그[1]": ["[[PERSON_9]]"]}


@pytest.mark.anyio
async def test_empty_list_field() -> None:
    store = InMemoryVaultStore()
    r = await tokenize_fields({"태그": []}, owner_id="u1", store=store)
    assert r.texts == {"태그": []}


@pytest.mark.anyio
async def test_bad_field_type_is_rejected() -> None:
    """조용히 넘기면 dict 의 키만 치환되는 식으로 이상하게 동작한다."""
    store = InMemoryVaultStore()
    with pytest.raises(TypeError):
        await tokenize_fields({"태그": {"a": "b"}}, owner_id="u1", store=store)  # type: ignore[dict-item]
    with pytest.raises(TypeError):
        await tokenize_fields({"태그": [1, 2]}, owner_id="u1", store=store)  # type: ignore[list-item]
