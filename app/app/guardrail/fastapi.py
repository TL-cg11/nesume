"""가드레일을 HTTP 요청에 붙이는 얇은 어댑터.

★ 가드레일 **본체는 FastAPI 를 모른다.** 순수 파이썬이라 DB·웹 없이 테스트된다.
  웹에 붙이는 데 필요한 값(요청 ID·세션·평가 트래픽 여부)만 여기서 꺼내 쓴다.
  그래서 이 파일만 FastAPI 를 import 하고, 패키지 `__init__` 에서는 내보내지 않는다.

B16 평가 러너 요청(2026-10-26)으로 세 가지를 연결한다.

    감사 로그   Guardrail(audit=DbAuditSink()) — 지금까지 기본값이라 한 줄도 안 남았다
    요청 ID     감사 로그 request_id 를 HTTP X-Request-ID 와 같게
    평가 트래픽  토큰(D7 test 그룹)으로 is_test 를 정해 지표에서 분리
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from fastapi import Header, HTTPException, status

from app.core.context import get_request_id
from app.guardrail.multiturn import InMemoryTurnStore
from app.guardrail.pipeline import TEST_SESSION_PREFIX, Guardrail, RequestContext

#: 세션 식별자를 받는 헤더. 평가 러너(B16)와 화면이 같은 이름을 쓴다.
SESSION_HEADER = "X-Session-Id"


@lru_cache(maxsize=1)
def _shared() -> Guardrail:
    """앱 전체가 공유하는 가드레일. 요청마다 새로 만들지 않는다.

    ``DbAuditSink`` 는 자기 세션을 직접 연다(`session_factory=SessionLocal`).
    그래서 요청 단위 세션에 묶이지 않고 여기 한 번만 만들어 둘 수 있다.

    ★ 대화 이력(A12)은 **메모리**다. 한 워커 안에서는 정확하지만 워커가 여러 개면
      같은 세션이 다른 워커로 갈 때 이력이 끊긴다. D7 세션 저장소가 준비되면
      그 구현을 주입한다 (docs/A12.md 6장).
    """
    from app.config import get_settings
    from app.features.audit.sink import DbAuditSink
    from app.guardrail.bedrock import build_provider
    from app.guardrail.llm_client import LlmClient
    from app.guardrail.rails.llama_guard import build_output_rail
    from app.retrieval.embedder import get_embedder
    from app.retrieval.search import build_retriever

    settings = get_settings()
    # A2 제공자 주입 지점. LLM_PROVIDER=none(기본)이면 지금까지와 같은 NotConfiguredProvider 다
    llm = LlmClient(provider=build_provider(settings))
    # C6 개인 검색 주입 지점 (C 요청 2026-11-02). EMBEDDING_URL 이 비면 get_embedder() 가
    # None → build_retriever() 도 None → 검색 단계 생략(지금까지와 같은 동작).
    #
    # ★ 인자 없는 build_retriever() 를 쓰지 않는다. 기본값이 embedder=None 이라
    #   설정과 무관하게 **항상** None 이 되어, 붙여도 개인 검색이 영원히 켜지지 않는다.
    #   설정을 읽는 get_embedder() 를 거쳐야 EMBEDDING_URL 이 있을 때 실제로 켜진다.
    # D19 출력 레일. LLAMA_GUARD_ENABLED=false(기본)면 None → A5 출력 검사만(기존 동작)
    return Guardrail(
        llm=llm,
        retriever=build_retriever(get_embedder()),
        audit=DbAuditSink(),
        history=InMemoryTurnStore(),
        output_rail=build_output_rail(settings),
    )


@lru_cache(maxsize=1)
def _limited() -> Guardrail:
    """C7 레이트리밋 래퍼 + D16 세션 차단 래퍼를 씌운 것. LLM 엔드포인트는 모두 이 의존성으로 받아 둘 다
    피할 수 없다.

    바깥이 C7 이다(C7 테스트가 바깥 타입을 본다): C7 한도 → D16 차단 목록 조회 → 가드레일 →
    D16(카나리·임계치면 자동 차단+알림) → C7 기록(위반 누적).
    D16 은 임계치 판정에 이번 위반을 더해 본다(session_block._c7_limit_reached).
    """
    from app.core.session_block import SessionBlockGuardrail
    from app.features.ratelimit.guard import RateLimitedGuardrail

    return RateLimitedGuardrail(SessionBlockGuardrail(_shared()))  # type: ignore[arg-type,return-value]


def get_guardrail() -> Guardrail:
    """테스트에서 갈아끼울 수 있게 의존성으로 뺀다.

    C13 ②: A5 응답 검사가 볼 카나리 토큰을 매 요청 직전에 채운다. 토큰은 DB에만 있고(C12 시드),
    5분 캐시라 DB를 매번 읽지 않는다. 시드 Job이 앱보다 늦게 돌아도(post-upgrade) 5분 안에 켜진다.
    C7: 돌려주는 것은 레이트리밋 래퍼다(같은 `_shared()` 가드레일을 감싼다).
    """
    from app.retrieval import canary

    _shared().canaries = canary.tokens.get()
    return _limited()


def _as_uuid(value: str) -> uuid.UUID:
    """HTTP 요청 ID 를 감사 로그의 UUID 컬럼에 넣을 수 있는 형태로.

    미들웨어가 만드는 기본값은 ``uuid4().hex`` 라 그대로 변환된다. 클라이언트가
    UUID 가 아닌 값을 보내면(헤더 형식은 그것도 허용한다) 새로 만든다 — 컬럼이
    UUID 라 달리 방법이 없다. **평가 러너는 UUID 형식으로 보내야 로그와 이어진다.**
    """
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return uuid.uuid4()


def build_context(
    *,
    feature: str,
    user_id: str,
    role: str,
    session_id: str | None,
    is_test: bool,
) -> RequestContext:
    """요청 하나를 식별하는 값을 모은다.

    ★ ``is_test`` 는 **토큰에서 온다** (D7 `cognito:groups` 의 test 그룹).
      2026-10-26 에는 D7 이 없어 세션 접두어로 판단했는데, 그러면 **일반 사용자가
      헤더를 흉내 내 자기 트래픽을 지표에서 뺄 수 있었다.** 이제 사용자가 못 고치는
      값(토큰)이 정한다.

    ★ 세션 접두어는 그 값에 **맞춰 준다.** ``audit_logs`` 의 CHECK 제약이
      ``(session_id LIKE 'test-%') = is_test`` 로 양방향이라 둘이 어긋나면 INSERT 가
      거부되고, 그 거부는 요청이 끝난 뒤 `finally` 에서 터진다. 받은 헤더를 그대로
      믿지 않고 여기서 맞추면 어긋날 수가 없다.

      평가 계정이 아닌 사람이 ``test-`` 로 시작하는 세션을 보내면 **접두어를 떼고**,
      평가 계정인데 접두어가 없으면 **붙인다.**
    """
    request_id = _as_uuid(get_request_id())
    base = (session_id or "").strip().removeprefix(TEST_SESSION_PREFIX)

    if is_test:
        # 평가 트래픽인데 세션이 비어 있으면 요청 ID 로 하나 만든다 —
        # 접두어만 있는 세션("test-")은 서로 구분이 안 된다
        session = TEST_SESSION_PREFIX + (base or request_id.hex[:12])
    else:
        session = base

    return RequestContext(
        user_id=user_id,
        role=role,
        feature=feature,
        session_id=session,
        is_test=is_test,
        request_id=request_id,
    )


def guardrail_kwargs(user: object, session_id: str | None) -> dict[str, object]:
    """서비스 호출에 넘길 컨텍스트 값 묶음.

    세 기능(A7·A11·A13)이 같은 값을 넘기므로 한곳에서 만든다.
    세션 식별자가 규약에 어긋나면 **여기서 400 으로 막는다** — 서비스 안쪽에서
    터지면 사용자는 500(서버 오류)으로 보게 된다.
    """
    session = (session_id or "").strip()
    if len(session) > 128:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{SESSION_HEADER} 가 너무 깁니다")

    ctx = build_context(
        feature="",  # 실제 feature 는 서비스가 채운다. 여기서는 검증만 한다
        user_id=getattr(user, "sub", ""),
        role=str(getattr(user, "role", "")),
        session_id=session,
        # ★ 헤더가 아니라 토큰이 정한다 (D7). 사용자가 고칠 수 없는 값이어야
        #   평가 지표를 사용자가 흔들 수 없다
        is_test=bool(getattr(user, "is_test", False)),
    )
    return {
        "user_id": ctx.user_id,
        "role": ctx.role,
        "session_id": ctx.session_id,
        "is_test": ctx.is_test,
        "request_id": ctx.request_id,
    }


def session_header(
    x_session_id: str | None = Header(default=None, alias=SESSION_HEADER),
) -> str | None:
    """세션 식별자 헤더. 없으면 None — 세션 없는 단발 요청이다."""
    return x_session_id


__all__ = [
    "SESSION_HEADER",
    "build_context",
    "guardrail_kwargs",
    "get_guardrail",
    "session_header",
]
