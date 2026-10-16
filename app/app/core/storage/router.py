"""다운로드 엔드포인트 (B6). 로그인한 발급자 본인만, 1회용 토큰으로 파일을 받는다.

브라우저 링크로는 Authorization 헤더를 보낼 수 없으므로 화면은 fetch로 받아 저장한다.
실패 사유(무효·만료·사용됨·타인)는 구분하지 않고 404로 응답한다.
다운로드 로그 기록(spec 3.2)은 저장 위치 확정 후 B12에서 추가한다.
"""
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.core.storage import objects, tokens
from app.db import get_db

router = APIRouter(prefix="/downloads", tags=["downloads"])
_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


@router.get("/{token}")
def download(token: str, user: AuthenticatedUser, db: Annotated[Session, Depends(get_db)]):
    redeemed = tokens.redeem(db, user.sub, token)
    if redeemed is None:
        raise _NOT_FOUND
    # 사용 처리를 먼저 확정해 같은 토큰의 재사용을 막는다
    db.commit()
    try:
        chunks = objects.open_object(redeemed.object_key)
    except objects.ObjectNotFound:
        raise _NOT_FOUND from None
    return StreamingResponse(
        chunks,
        media_type=redeemed.content_type,
        headers={
            # RFC 5987: 한글 파일명
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(redeemed.filename)}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
