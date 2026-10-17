"""PII 공용 모듈 — 세 파트가 함께 쓴다.

공개 연산은 다섯 개다. 여섯 번째가 필요해지면 그건 모듈 경계를 넘는 신호다.

    validate_input(text)                  받으면 안 되는 입력인가       (동기, 부작용 없음)
    detect(text)                          찾기만 한다                   (동기, 부작용 없음)
    mask(text)                            되돌릴 수 없게 가린다         (동기, 부작용 없음)
    tokenize(text, owner_id=, store=)     LLM에 보내기 직전             (비동기, 치환표 생성)
    detokenize(text, vault_id, owner_id=) 사용자에게 돌려주기 직전      (비동기, 치환표 조회)

호출 순서 계약 (제안서 8장):

    1. validate_input   거절 대상이면 여기서 끝
    2. tokenize         여기부터 원문은 사라진다
    3. 프롬프트 조립     외부 텍스트는 데이터로 감싼다
    4. LLM 호출         모델은 토큰만 본다
    5. 출력 검사(A5)     ★ 복원 전에 검사한다
    6. detokenize       복원 + 조사 보정

5번과 6번의 순서를 바꾸지 않는다. 복원 후에 검사하면 방금 되돌려놓은 진짜 이름이
전부 경고로 뜬다.

이 모듈이 하지 않는 일: 저장(2번 파트), LLM 호출(가드레일), 로그 쓰기(호출자),
HTTP 상태코드 결정(호출자).
"""

from app.pii.core import detect, mask, validate_input
from app.pii.tokens import (
    VaultExpired,
    VaultOwnerMismatch,
    detokenize,
    fix_korean_particles,
    tokenize,
)
from app.pii.types import (
    BlockedKind,
    DetokenizeResult,
    Hit,
    PiiKind,
    TokenizeResult,
    ValidationResult,
)
from app.pii.vault import (
    DEFAULT_TTL_SECONDS,
    TOKEN_FORMAT_VERSION,
    InMemoryVaultStore,
    Vault,
    VaultStore,
)

__all__ = [
    # 연산
    "validate_input",
    "detect",
    "mask",
    "tokenize",
    "detokenize",
    "fix_korean_particles",
    # 타입
    "PiiKind",
    "Hit",
    "BlockedKind",
    "ValidationResult",
    "TokenizeResult",
    "DetokenizeResult",
    # 치환표
    "Vault",
    "VaultStore",
    "InMemoryVaultStore",
    "TOKEN_FORMAT_VERSION",
    "DEFAULT_TTL_SECONDS",
    # 예외
    "VaultExpired",
    "VaultOwnerMismatch",
]
