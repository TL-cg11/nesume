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
#: LLM 호출용 임시 치환표의 수명이다.
DEFAULT_TTL_SECONDS = 1800

#: 만료 없음. 저장용 치환표에 쓴다.
#:
#: 자소서 본문을 토큰 상태로 **저장**하면(B7 설계), 그 치환표는 문서가 살아 있는 동안
#: 함께 살아 있어야 한다. 30분 뒤 지우면 그 자소서는 영구히 복원 불가가 된다.
#: 반대로 LLM 호출용 임시 치환표는 오래 남을수록 유출 창이 넓어지므로 TTL 을 둔다.
#:
#: 수명은 치환표 자체의 속성이므로 만료 판정(`Vault.is_expired`)과 함께 A1 에 둔다.
#: 저장소가 "100년 뒤"로 우회하면 판정 규칙이 두 곳으로 갈라진다.
NO_EXPIRY: None = None


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
    #: epoch seconds. None 이면 만료 없음 — 저장용 치환표 (NO_EXPIRY 참조)
    expires_at: float | None
    format_version: int = TOKEN_FORMAT_VERSION

    @property
    def is_permanent(self) -> bool:
        """저장용 치환표인가. 삭제 배치가 건너뛰어야 하는 대상이다."""
        return self.expires_at is None

    def is_expired(self, now: float | None = None) -> bool:
        if self.expires_at is None:
            return False
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

    async def save(self, vault: Vault) -> None:
        """``expires_at`` 이 None 인 치환표는 **만료 없음**(저장용)이다.

        ★ 주기 삭제 배치(B20)는 ``expires_at IS NULL`` 행을 건너뛰어야 한다.
          지우면 그 자소서는 영구히 복원 불가가 된다.
        """
        ...

    async def load(self, vault_id: str) -> Vault | None:
        """없거나 이미 만료돼 삭제되었으면 None.

        만료 판정은 ``Vault.is_expired()`` 를 쓴다. 저장소가 직접 시각을 비교하면
        만료 없음(None) 처리가 두 곳으로 갈라진다.
        """
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
        if vault.is_expired():  # 만료 없음(None)이면 False 를 돌려준다
            # 만료된 것은 실제로 지운다. 표시만 하고 남겨두면 지운 게 아니다 (제안서 6장).
            del self._items[vault_id]
            return None
        return vault

    async def delete(self, vault_id: str) -> None:
        self._items.pop(vault_id, None)
