"""PII 모듈 단위 테스트.

DB도 네트워크도 쓰지 않는다. 치환표는 InMemoryVaultStore 로 대체한다.
"""

from __future__ import annotations

import pytest

from app.pii import (
    InMemoryVaultStore,
    VaultExpired,
    VaultOwnerMismatch,
    detect,
    detokenize,
    fix_korean_particles,
    mask,
    tokenize,
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

def test_mask_is_irreversible() -> None:
    masked = mask("연락처 010-1234-5678")
    assert "010" not in masked or "*" in masked
    assert "5678" in masked, "대조용 뒷자리는 남긴다"


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


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
