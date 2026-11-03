"""C12·C13 — 카나리(미끼) 토큰과 검색 결과 검사 (docs/C12_C13.md).

미끼는 **기밀 등급**(matrix.yaml에서 모든 역할 block)이라 정상이면 어떤 검색·응답에도 나오지 않는다.
나오면 = 권한 필터가 뚫렸다. 진짜 기밀 데이터는 0건이라 오탐이 없다.

- 토큰: 시드 배치가 처음 실행될 때 `secrets`로 만들어 **DB에만** 둔다(저장소에 없음 — 코드를 읽어도 모른다).
- 검색 검사(C13 ①·결정3): 행마다 같은 매트릭스로 "이 역할이 받을 수 있었나"를 다시 확인한다.
  거르는 곳을 하나 더 두는 게 아니라 **나올 수 없는 결과**를 잡아 요청을 막는 검사다.
- 응답 검사(C13 ②): A5가 `Guardrail.canaries`로 한다. 여기선 토큰 목록을 5분 캐시로 준다.
- 로그에는 토큰 앞 4자리만(`NSM-` 다음) — 로그가 새도 토큰 전체가 드러나지 않게.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.guardrail.schema import CANARY_RULE_ID
from app.models.embedding import UserProfileEmbedding
from app.policy.policy import Policy

log = logging.getLogger("nesume.security")

CANARY_OWNER = "system:canary"
CANARY_SOURCE_TYPE = "canary"
CANARY_GRADE = "confidential"
TOKEN_PATTERN = re.compile(r"NSM-CANARY-[0-9a-f]{12}")

#: 검색 결과에 미끼가 섞였다 (A5와 같은 규칙 ID → 감사 로그 `canary_hit`)
LEAK_CANARY = CANARY_RULE_ID
#: 미끼는 없지만 매트릭스상 받을 수 없는 행이 섞였다 (결정3, D10 §2 행 추가 요청)
FILTER_BYPASS = "AUTHZ_FILTER_BYPASS"

#: 토큰 목록을 다시 읽는 주기(초). 시드 Job이 앱보다 늦게 돌아도(helm post-upgrade) 이 안에 반영된다
TOKEN_TTL_SECONDS = 300


def load_tokens(session: Session) -> tuple[str, ...]:
    """DB의 미끼 문서에서 토큰을 읽는다. 시드 전이면 빈 튜플(= 검사할 토큰 없음, 지금 동작과 같음)."""
    rows = session.execute(
        select(UserProfileEmbedding.content).where(
            UserProfileEmbedding.owner_id == CANARY_OWNER,
            UserProfileEmbedding.source_type == CANARY_SOURCE_TYPE,
        )
    ).scalars()
    return tuple(sorted({t for content in rows for t in TOKEN_PATTERN.findall(content)}))


class TokenCache:
    """토큰 목록 TTL 캐시. 다시 읽다 실패하면 **마지막 값을 유지**하고 경고만 남긴다."""

    def __init__(
        self,
        loader: Callable[[], tuple[str, ...]],
        *,
        ttl: float = TOKEN_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loader = loader
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._value: tuple[str, ...] = ()
        self._loaded_at: float | None = None

    def get(self) -> tuple[str, ...]:
        now = self._clock()
        with self._lock:
            if self._loaded_at is not None and now - self._loaded_at < self._ttl:
                return self._value
            try:
                self._value = self._loader()
            except Exception:  # noqa: BLE001 — DB 오류로 요청이 죽지 않게. 이전 목록으로 계속 검사
                log.warning("canary token reload failed, keeping previous list", exc_info=True)
            self._loaded_at = now
            return self._value


def _db_tokens() -> tuple[str, ...]:
    from app.db import SessionLocal

    with SessionLocal() as db:
        return load_tokens(db)


#: 앱 전체가 공유하는 캐시(응답 검사용 `Guardrail.canaries`)
tokens = TokenCache(_db_tokens)


def violation(
    row, *, role: str, user_id: str, policy: Policy, known_tokens: Iterable[str] = ()
) -> str | None:
    """검색 결과 한 행이 이 요청에 나올 수 없는 행이면 규칙 ID, 정상이면 None.

    `row`는 `search_personal` 행(`source_type`·`grade`·`owner_id`·`content`).
    """
    if (
        row.source_type == CANARY_SOURCE_TYPE
        or row.owner_id == CANARY_OWNER
        or row.grade == CANARY_GRADE
        or any(t in row.content for t in known_tokens)
    ):
        return LEAK_CANARY
    decision, scope = policy.decision(role, row.grade)
    if decision == "block":
        return FILTER_BYPASS
    if scope == "own" and row.owner_id != user_id:
        return FILTER_BYPASS
    if scope == "shared":  # 개인 검색은 공유 경로를 WHERE에서 뺐다 → 나올 수 없다
        return FILTER_BYPASS
    return None


def report(rule_id: str, *, where: str, role: str, user_id: str, rows: list) -> None:
    """구조화 보안 이벤트(D16 알림이 이 로그를 받는다). 본문·토큰 전체는 남기지 않는다."""
    prefixes = sorted(
        {t.removeprefix("NSM-CANARY-")[:4] for r in rows for t in TOKEN_PATTERN.findall(r.content or "")}
    )
    log.warning(
        "security_event=%s where=%s role=%s user=%s rows=%d token_prefix=%s",
        "canary_hit" if rule_id == LEAK_CANARY else "filter_bypass",
        where, role, user_id, len(rows), ",".join(prefixes) or "-",
    )
