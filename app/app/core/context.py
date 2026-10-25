"""요청 범위 컨텍스트.

request_id는 미들웨어가 설정하고, 로그 포매터·에러 응답이 읽는다.
인증 정보(user_id, role, is_test)는 ContextVar 가 아니라 request.state(scope["state"])에 둔다.
get_current_user 가 동기 의존성(스레드풀)이라 ContextVar 가 미들웨어로 전파되지 않기 때문이다(D7).
"""
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """현재 요청의 request_id. 요청 밖(배치 등)에서는 '-'."""
    return request_id_var.get()
