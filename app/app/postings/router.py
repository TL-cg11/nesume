"""C4 — 공고 상세 API (화면용 원문 필드).

`GET /postings/{id}`: 공고에 적힌 글을 `라벨: 값`으로. 추천 화면 상세 보기가 쓴다
(docs C-frontend-wiring.md 8절).
A11 `/matching/analyze`의 키워드는 매칭용이라 화면 표시엔 쓰지 않는다. 권한 = `read.get_posting_detail`.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.db import get_db
from app.postings.read import get_posting_detail

router = APIRouter(prefix="/postings", tags=["postings"])
Db = Annotated[Session, Depends(get_db)]


class PostingField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    value: str


class PostingDetailOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    source: str
    company_name: str | None
    title: str | None
    job_name: str | None
    #: 직무내용 원문(수집 때 A1 mask 적용). 화면은 텍스트로만 표시(HTML 렌더링 금지)
    job_content: str | None
    fields: list[PostingField]
    #: 원문 링크(공채속보만, http/https만 저장됨)
    url: str | None
    is_active: bool


@router.get("/{posting_id}", response_model=PostingDetailOut)
def posting_detail(posting_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    detail = get_posting_detail(db, posting_id, user_id=user.sub)
    if detail is None:  # 없음/권한 없음 구분 안 함(존재 노출 방지)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "공고를 찾을 수 없습니다")
    return detail
