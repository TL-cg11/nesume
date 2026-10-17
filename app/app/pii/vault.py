"""치환표(Vault) 저장 포트.

제안서 v0.1 6장에서 "치환표를 어디에 둘 것인가"를 미정으로 남겼는데,
tasks.md v2 의 B7("PII 토큰↔원문 매핑 테이블 + KMS 컬럼 암호화")이 그 답이 되었다.
저장은 2번 파트가 맡고, 이 모듈은 저장소를 직접 알지 않는다.

그래서 여기에는 **인터페이스(포트)만** 둔다.
- 1번 파트: 아래 VaultStore 프로토콜에 맞춰 tokenize/detokenize 를 쓴다
- 2번 파트: B7에서 이 프로토콜을 구현한다 (Postgres + KMS)
- 테스트: InMemoryVaultStore 를 쓴다. DB 없이 돌아간다

이 분리 덕분에 PII 모듈은 DB도 KMS도 모른 채로 단위 테스트가 된다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

#: 토큰 형식 버전. 형식을 바꾸면 올린다 — 옛 형식 치환표도 복원되게 하기 위한 장치.
#: 제안서 11장 "토큰 형식 변경이 가장 위험하다" 참조.
TOKEN_FORMAT_VERSION = 1

#: 기본 만료 30분. 한 번의 편집 세션을 넘기지 않는 길이 (제안서 6장).
DEFAULT_TTL_SECONDS = 1800


@dataclass
class Vault:
    """토큰 → 원문 대응표.

    ★ 이 객체 자체가 복원 열쇠다. 금지 사항 네 가지 (제안서 3장):
      1. LLM 요청에 넣지 않는다
      2. 로그에 쓰지 않는다 — 항목 개수만 기록한다
      3. 클라이언트로 내려보내지 않는다
      4. 에러 메시지에 담지 않는다
    """

    id: str
    owner_id: str
    entries: dict[str, str]  # token -> 원문
    expires_at: float  # epoch seconds
    format_version: int = TOKEN_FORMAT_VERSION

    def is_expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 편의
        # 원문이 스택트레이스·로그로 새어나가는 사고를 구조적으로 막는다.
        return (
            f"Vault(id={self.id!r}, owner_id={self.owner_id!r}, "
            f"entries={len(self.entries)}개, expires_at={self.expires_at})"
        )


class VaultStore(Protocol):
    """치환표 저장소. 2번 파트(B7)가 구현한다.

    async 인 이유: 실제 구현은 DB·KMS 왕복이 있다. 메모리 구현도 같은 모양을 지켜
    호출부가 달라지지 않게 한다.
    """

    async def save(self, vault: Vault) -> None: ...

    async def load(self, vault_id: str) -> Vault | None:
        """없거나 이미 만료돼 삭제되었으면 None."""
        ...

    async def delete(self, vault_id: str) -> None: ...


@dataclass
class InMemoryVaultStore:
    """테스트·로컬 전용 구현. 프로세스가 죽으면 사라진다.

    운영에서는 쓰지 않는다 — 서버가 여러 대면 재시도가 깨진다 (제안서 6장 A안의 단점).
    """

    _items: dict[str, Vault] = field(default_factory=dict)

    async def save(self, vault: Vault) -> None:
        self._items[vault.id] = vault

    async def load(self, vault_id: str) -> Vault | None:
        vault = self._items.get(vault_id)
        if vault is None:
            return None
        if vault.is_expired():
            # 만료된 것은 실제로 지운다. 표시만 하고 남겨두면 지운 게 아니다 (제안서 6장).
            del self._items[vault_id]
            return None
        return vault

    async def delete(self, vault_id: str) -> None:
        self._items.pop(vault_id, None)
