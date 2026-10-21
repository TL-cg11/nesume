"""공통 에러 형식.

D가 추가하는 에러(AppError 계열, 422 검증, 500)는 아래 평면 형식으로 응답한다.
    {"detail": "<사용자용 메시지>", "code": "<snake_case>", "request_id": "<X-Request-ID>", "errors": [...]?}
B가 쓰는 HTTPException(detail=...)은 FastAPI 기본 응답({"detail": ...})을 그대로 둔다.
→ 어떤 경우에도 응답에 `detail`이 있다(web ApiError·B 테스트 호환).

500은 내부 정보를 노출하지 않고 로그에만 남긴다.
422 `errors`에는 입력 원문(input)을 넣지 않는다(PII 유입 방지).
"""
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.context import get_request_id

log = logging.getLogger("nesume.errors")


class AppError(Exception):
    """기능 코드가 던지는 기본 에러. status_code·code를 하위 클래스에서 고정한다."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        errors: list | dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.errors = errors


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"


INTERNAL_ERROR_MESSAGE = "서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."


def error_response(
    status_code: int,
    code: str,
    message: str,
    errors: list | dict | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"detail": message, "code": code, "request_id": get_request_id()}
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def _sanitize_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # pydantic 오류에는 'input'(원문)과 'ctx'(예외 객체)가 포함된다. 원문은 돌려주지 않는다.
    return [{k: v for k, v in e.items() if k in ("type", "loc", "msg")} for e in errors]


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.errors)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            422,
            "validation_error",
            "요청 형식이 올바르지 않습니다.",
            _sanitize_validation_errors(exc.errors()),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", extra={"fields": {"error_type": type(exc).__name__}})
        return error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE)
