"""B12 PDF API. 자소서 라우터 아래(/resumes/{id}/pdf)에 붙어 main.py 등록 없이 동작한다."""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.core.errors import AppError
from app.db import get_db
from app.features.pdf import render, service
from app.features.resumes import pii_hooks

router = APIRouter(tags=["pdf"])
_EMPTY = "PDF로 만들 내용이 없습니다. 문항에 내용을 저장한 뒤 다시 시도해 주세요."


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=50)
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=254)


class PdfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 넣을 버전(문항당 하나). 비우면 문항별 최신. 제출용 연락처는 저장하지 않고 PDF 상단에만
    version_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    contact: ContactIn = ContactIn()


class PdfOut(BaseModel):
    download_path: str  # 화면은 로그인 상태로 GET(1회용, 10분)
    expires_at: datetime
    filename: str


@router.post("/{resume_id}/pdf", response_model=PdfOut, status_code=status.HTTP_201_CREATED)
def export_pdf(resume_id: uuid.UUID, payload: PdfRequest, user: AuthenticatedUser,
               db: Annotated[Session, Depends(get_db)]):
    c = payload.contact
    try:
        out = service.export_pdf(db, user.sub, resume_id, version_ids=payload.version_ids,
                                 contact=render.Contact(c.name.strip(), c.phone.strip(), c.email.strip()))
    except service.VersionsInvalid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "넣을 버전을 다시 골라 주세요(문항마다 하나, 이 자소서의 버전만).") from None
    except service.NothingToExport:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _EMPTY) from None
    except pii_hooks.SensitiveInputBlocked:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "주민번호·계좌번호 등 민감정보는 PDF에 넣을 수 없습니다.") from None
    except render.PdfUnavailable:
        raise AppError("PDF 기능을 준비하고 있습니다. 잠시 후 다시 시도해 주세요.", code="pdf_unavailable",
                       status_code=503) from None
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return PdfOut(download_path=f"/downloads/{out.token}", expires_at=out.expires_at, filename=out.filename)
