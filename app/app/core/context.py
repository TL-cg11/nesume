"""요청 범위 컨텍스트.

request_id는 미들웨어가 설정하고, 로그 포매터·에러 응답이 읽는다.
인증 정보(role, user_id)는 D7에서 같은 방식으로 추가한다.
"""
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """현재 요청의 request_id. 요청 밖(배치 등)에서는 '-'."""
    return request_id_var.get()
