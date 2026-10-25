"""X-Request-ID 미들웨어 + 접근 로그.

- 클라이언트가 보낸 X-Request-ID가 형식에 맞으면 그대로 쓰고, 아니면 새로 만든다.
- 응답 헤더 X-Request-ID로 돌려준다. 에러 응답 본문에도 같은 값이 들어간다(errors.py).
- 요청 1건당 접근 로그 1줄(method, path, status, duration_ms, user_id, role, is_test)을 남긴다.
  질의 본문·토큰·이메일은 기록하지 않는다.
  user_id/role/is_test 는 D7 get_current_user 가 scope["state"]에 넣는다.
"""
import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

log = logging.getLogger("nesume.access")


def new_request_id() -> str:
    return uuid.uuid4().hex


class RequestIdMiddleware:
    """순수 ASGI 미들웨어. BaseHTTPMiddleware보다 contextvar 전파가 단순하다."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        request_id = incoming if incoming and _VALID_REQUEST_ID.match(incoming) else new_request_id()

        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_holder = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            client = scope.get("client")
            state = scope.get("state") or {}
            log.info(
                "http_request",
                extra={
                    "fields": {
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "status": status_holder["status"],
                        "duration_ms": duration_ms,
                        "client_ip": client[0] if client else None,
                        "user_id": state.get("user_id"),
                        "role": state.get("role"),
                        "is_test": state.get("is_test"),
                    }
                },
            )
            request_id_var.reset(token)
