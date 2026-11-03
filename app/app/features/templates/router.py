"""프롬프트 템플릿 관리 API (tasks B9, spec 3.6). 운영자 전용, 활성 전환은 MFA 세션.

main.py(D 소유) 등록은 D에 요청한다. A는 HTTP가 아니라 service.get_active_template로 읽는다.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import CurrentUser, Role, require_operator_mfa, require_role
from app.core.errors import AppError
from app.db import get_db
from app.features.templates import service
from app.features.templates.schemas import TemplateCreate, TemplateNewVersion, TemplateOut, TemplateSummary

router = APIRouter(prefix="/templates", tags=["templates"])

Db = Annotated[Session, Depends(get_db)]
Operator = Annotated[CurrentUser, Depends(require_role(Role.OPERATOR))]
OperatorMfa = Annotated[CurrentUser, Depends(require_operator_mfa)]
_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def _mismatch(e: service.VariablesMismatch) -> AppError:
    return AppError("본문의 {{변수}}와 변수 목록이 일치하지 않습니다.", code="template_variables_mismatch",
                    status_code=422, errors={"missing": sorted(e.missing), "unused": sorted(e.unused)})


@router.get("", response_model=list[TemplateSummary])
def list_templates(_: Operator, db: Db):
    return service.list_names(db)


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(payload: TemplateCreate, user: Operator, db: Db):
    try:
        return service.create(db, user.sub, **payload.model_dump())
    except service.TemplateExists:
        raise AppError("같은 이름의 템플릿이 있습니다. 새 버전으로 작성해 주세요.", code="template_exists",
                       status_code=409) from None
    except service.VariablesMismatch as e:
        raise _mismatch(e) from None


@router.get("/{name}/versions", response_model=list[TemplateOut])
def list_versions(name: str, _: Operator, db: Db):
    rows = service.list_versions(db, name)
    if not rows:
        raise _NOT_FOUND
    return rows


@router.post("/{name}/versions", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def create_version(name: str, payload: TemplateNewVersion, user: Operator, db: Db):
    """수정 = 새 버전(비활성). 활성 전환은 별도(MFA)."""
    try:
        t = service.new_version(db, user.sub, name, **payload.model_dump())
    except service.VariablesMismatch as e:
        raise _mismatch(e) from None
    if t is None:
        raise _NOT_FOUND
    return t


@router.put("/{template_id}/activate", response_model=TemplateOut)
def activate(template_id: uuid.UUID, _: OperatorMfa, db: Db):
    """활성 버전 전환. 운영자 MFA 세션만(spec 3.6). 운영자가 아니면 403(C11-AUTHZ-07)."""
    t = service.activate(db, template_id)
    if t is None:
        raise _NOT_FOUND
    return t
