"""공통 응답 스키마.

성공 응답은 기능별 모델을 그대로 반환한다(별도 래핑 없음).
에러 응답은 ErrorResponse 형식(평면, detail 필수). 목록은 Page[T]를 쓴다.
"""
from fastapi import Query
from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str = Field(description="사용자에게 보여줄 수 있는 한 줄 설명")
    code: str = Field(description="기계가 읽는 에러 코드(snake_case). 예: not_found, validation_error")
    request_id: str = Field(description="X-Request-ID와 같은 값. 문의·로그 추적용")
    errors: list | dict | None = Field(default=None, description="필드별 상세. 입력 원문은 넣지 않는다")


class PageParams(BaseModel):
    """목록 API 공통 페이지 파라미터. `params: PageParams = Depends()`로 사용."""

    limit: int = Query(20, ge=1, le=100)
    offset: int = Query(0, ge=0)


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
