"""치환과 복원 — tokenize / detokenize.

이 두 함수만 치환표를 다루므로 async 다. 나머지 세 연산은 core.py 에 있다.
"""

from __future__ import annotations

import re
import secrets
import time

from app.pii.rules import scan
from app.pii.types import (
    Hit,
    PiiKind,
    TOKENIZED_KINDS,
    DetokenizeResult,
    FieldsDetokenizeResult,
    FieldsTokenizeResult,
    TokenizeResult,
)
from app.pii.vault import (
    DEFAULT_TTL_SECONDS,
    TOKEN_FORMAT_VERSION,
    Vault,
    VaultStore,
)
from collections.abc import Mapping

#: 토큰 형식 `[[PERSON_1]]`.
#: 대괄호 둘 — 하나면 마크다운 링크와 겹친다.
#: 영문 대문자 — 모델이 번역하거나 다듬을 가능성이 가장 낮다.
#: 일련번호는 1부터, 문서 안에서만 의미를 갖는다. (제안서 5장)
_TOKEN_RE = re.compile(r"\[\[([A-Z]+)_(\d+)\]\]")


def _make_token(kind: PiiKind, index: int) -> str:
    return f"[[{kind}_{index}]]"


class VaultOwnerMismatch(Exception):
    """치환표 주인과 복원 요청자가 다르다.

    정상 흐름에서는 일어날 수 없으므로 발생 자체가 신호다 (제안서 7장).
    조용히 빈 결과를 돌려주지 않고 예외로 멈춘다.
    """


class VaultExpired(Exception):
    """치환표가 만료됐다. 부분 복원은 더 나쁘므로 시도하지 않는다."""


class _Tokenizer:
    """치환 상태를 들고 여러 텍스트에 걸쳐 재사용한다.

    ``seen`` 과 ``counters`` 를 공유하는 것이 핵심이다. 덕분에 필드가 여럿이어도
    같은 값은 같은 토큰을 받고 번호는 1부터 이어진다.
    """

    def __init__(self, targets: set[str]) -> None:
        self.targets = targets
        self.entries: dict[str, str] = {}  # token -> 원문
        self._seen: dict[tuple[str, str], str] = {}  # (kind, 원문) -> token
        self._counters: dict[str, int] = {}
        self.counts: dict[str, int] = {}

    def run(self, text: str) -> tuple[str, list[Hit]]:
        hits: list[Hit] = []
        out: list[str] = []
        cursor = 0

        for span in scan(text):
            kind = span.rule.kind
            if kind not in self.targets:
                continue

            key = (kind, span.value)
            token = self._seen.get(key)
            if token is None:
                self._counters[kind] = self._counters.get(kind, 0) + 1
                token = _make_token(kind, self._counters[kind])
                self._seen[key] = token
                self.entries[token] = span.value

            out.append(text[cursor : span.start])
            out.append(token)
            cursor = span.end

            hits.append(
                Hit(
                    kind=kind,
                    rule_id=span.rule.rule_id,
                    start=span.start,
                    end=span.end,
                    confidence=span.rule.confidence,
                    token=token,
                )
            )
            self.counts[kind] = self.counts.get(kind, 0) + 1

        out.append(text[cursor:])
        return "".join(out), hits


def _new_vault(owner_id: str, entries: dict[str, str], ttl_seconds: int | None) -> Vault:
    return Vault(
        id=secrets.token_urlsafe(24),  # 순번이면 남의 치환표를 열어볼 수 있다
        owner_id=owner_id,
        entries=entries,
        # None 이면 만료 없음 — 저장용 치환표 (vault.NO_EXPIRY)
        expires_at=None if ttl_seconds is None else time.time() + ttl_seconds,
        format_version=TOKEN_FORMAT_VERSION,
    )


async def tokenize(
    text: str,
    *,
    owner_id: str,
    store: VaultStore,
    kinds: tuple[PiiKind, ...] | None = None,
    ttl_seconds: int | None = DEFAULT_TTL_SECONDS,
) -> TokenizeResult:
    """LLM에 보내기 직전에 부른다.

    같은 값은 같은 토큰을 받는다 — 한 문서에서 "김철수"가 세 번 나오면 세 번 다
    ``[[PERSON_1]]`` 이다. 다른 토큰을 주면 모델이 세 사람으로 읽는다.

    치환표는 문서 단위로 새로 만든다. 요청 사이에 번호를 이어받지 않는다 —
    이어받으면 같은 사람이 항상 ``[[PERSON_1]]`` 이 되어 토큰 자체가 식별자가 된다
    (제안서 4장).

    ``ttl_seconds=None`` 이면 만료 없는 치환표를 만든다. 토큰 상태로 **저장**하는
    경우(B7)에 쓴다 — 30분 뒤 지우면 그 자소서는 영구히 복원 불가가 된다.
    """
    tokenizer = _Tokenizer(set(kinds or TOKENIZED_KINDS))
    tokenized, hits = tokenizer.run(text)

    vault = _new_vault(owner_id, tokenizer.entries, ttl_seconds)
    await store.save(vault)

    return TokenizeResult(
        text=tokenized, vault_id=vault.id, hits=hits, counts=tokenizer.counts
    )


async def tokenize_fields(
    fields: Mapping[str, str],
    *,
    owner_id: str,
    store: VaultStore,
    kinds: tuple[PiiKind, ...] | None = None,
    ttl_seconds: int | None = DEFAULT_TTL_SECONDS,
) -> FieldsTokenizeResult:
    """여러 필드를 **치환표 하나로** 묶어 치환한다 (B4·B5 요청).

    자소서 한 건은 문항이 여럿이고 같은 전화번호가 여러 문항에 나온다.
    필드마다 ``tokenize`` 를 따로 부르면 같은 값이 문항마다 다른 토큰을 받아
    모델이 다른 사람으로 읽고, 치환표도 문항 수만큼 생긴다.

    호출자가 필드를 구분자로 이어 붙여 한 번에 넣고 다시 나누는 방법은 쓰지 않는다 —
    그 구분자가 본문에 섞여 있거나 개인정보가 경계에 걸리면 깨진다.

    번호는 **입력 순서대로** 1부터 이어진다. dict 는 입력 순서를 유지하므로
    같은 입력에 대해 결과가 항상 같다.
    """
    tokenizer = _Tokenizer(set(kinds or TOKENIZED_KINDS))

    texts: dict[str, str] = {}
    hits: dict[str, list[Hit]] = {}
    for name, text in fields.items():
        texts[name], hits[name] = tokenizer.run(text)

    vault = _new_vault(owner_id, tokenizer.entries, ttl_seconds)
    await store.save(vault)

    return FieldsTokenizeResult(
        texts=texts, vault_id=vault.id, hits=hits, counts=tokenizer.counts
    )


async def _load_vault(store: VaultStore, vault_id: str, owner_id: str) -> Vault:
    vault = await store.load(vault_id)
    if vault is None:
        raise VaultExpired(f"치환표를 찾을 수 없거나 만료되었습니다 (id={vault_id})")
    if vault.owner_id != owner_id:
        raise VaultOwnerMismatch("치환표 소유자와 복원 요청자가 다릅니다")
    return vault


def _restore(text: str, vault: Vault, fix_particles: bool) -> tuple[str, list[str]]:
    unresolved: list[str] = []

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        value = vault.entries.get(token)
        if value is None:
            unresolved.append(token)
            return token  # 그대로 둔다. 호출자가 unresolved 를 보고 판단한다
        return value

    restored = _TOKEN_RE.sub(replace, text)
    if fix_particles:
        restored = fix_korean_particles(restored)

    # 중복 제거하되 순서는 유지한다
    return restored, list(dict.fromkeys(unresolved))


async def detokenize(
    text: str,
    vault_id: str,
    owner_id: str,
    *,
    store: VaultStore,
    fix_particles: bool = True,
) -> DetokenizeResult:
    """LLM 응답을 사용자에게 돌려주기 직전에 부른다.

    ★ 출력 검사(A5)를 이 함수보다 **먼저** 해야 한다. 복원 후에 검사하면 방금
      되돌려놓은 진짜 이름과 전화번호가 검사에 걸려 전부 경고로 뜬다 (제안서 8장).

    owner_id 를 받는 이유: vault_id 만으로 열면 그 값이 유출됐을 때 남의 원문이
    복원된다. 치환표 주인과 복원 요청자가 같은지 대조한다.
    """
    vault = await _load_vault(store, vault_id, owner_id)
    restored, unresolved = _restore(text, vault, fix_particles)
    return DetokenizeResult(text=restored, unresolved=unresolved)


async def detokenize_fields(
    fields: Mapping[str, str],
    vault_id: str,
    owner_id: str,
    *,
    store: VaultStore,
    fix_particles: bool = True,
) -> FieldsDetokenizeResult:
    """``tokenize_fields`` 로 묶은 필드들을 한 번에 복원한다.

    치환표를 한 번만 읽는다. 필드마다 ``detokenize`` 를 부르면 같은 치환표를
    문항 수만큼 복호화하게 된다 (B7 은 KMS 를 거친다).
    """
    vault = await _load_vault(store, vault_id, owner_id)

    texts: dict[str, str] = {}
    unresolved: dict[str, list[str]] = {}
    for name, text in fields.items():
        texts[name], missing = _restore(text, vault, fix_particles)
        if missing:
            unresolved[name] = missing

    return FieldsDetokenizeResult(texts=texts, unresolved=unresolved)


# --------------------------------------------------------------------------
# 한국어 조사 보정
# --------------------------------------------------------------------------
# 모델은 `[[PERSON_1]]` 을 받침 있는 단어로 보고 "은"을 붙인다. 복원하면 받침 없는
# "김철수"에 "은"이 남아 "김철수은" 같은 문장이 된다. 자소서는 문장 품질이 곧
# 결과물이므로 이건 그냥 버그다. (제안서 5장)
#
# 호출자 쪽에 맡기면 1번 파트는 하고 2번 파트는 안 하는 상태가 되므로 모듈 안에 둔다.
# 끄고 싶으면 fix_particles=False.

_PARTICLE_PAIRS: tuple[tuple[str, str], ...] = (
    ("은", "는"),  # (받침 있을 때, 없을 때)
    ("이", "가"),
    ("을", "를"),
    ("과", "와"),
)

_PARTICLE_RE = re.compile(
    r"([가-힣])(은|는|이|가|을|를|과|와|으로|로)(?![가-힣])"
)


def _has_final_consonant(ch: str) -> bool:
    """한글 음절에 받침이 있는가."""
    code = ord(ch)
    if not (0xAC00 <= code <= 0xD7A3):
        return False
    return (code - 0xAC00) % 28 != 0


def _is_rieul_final(ch: str) -> bool:
    """받침이 ㄹ인가. '으로/로' 는 ㄹ 받침 뒤에서 '로' 를 쓴다."""
    code = ord(ch)
    if not (0xAC00 <= code <= 0xD7A3):
        return False
    return (code - 0xAC00) % 28 == 8  # 8 = ㄹ


def fix_korean_particles(text: str) -> str:
    """복원된 단어의 받침에 맞게 뒤따르는 조사를 고른다.

    토큰이 아닌 원래 문장의 조사도 함께 검사하게 되지만, 올바른 조사는 그대로
    유지되므로 결과가 달라지지 않는다.
    """

    def pick(match: re.Match[str]) -> str:
        last_char, particle = match.group(1), match.group(2)
        has_final = _has_final_consonant(last_char)

        if particle in {"으로", "로"}:
            # ㄹ 받침은 '로', 그 외 받침은 '으로', 받침 없으면 '로'
            correct = "로" if (not has_final or _is_rieul_final(last_char)) else "으로"
            return f"{last_char}{correct}"

        for with_final, without_final in _PARTICLE_PAIRS:
            if particle in (with_final, without_final):
                return f"{last_char}{with_final if has_final else without_final}"

        return match.group(0)

    return _PARTICLE_RE.sub(pick, text)
