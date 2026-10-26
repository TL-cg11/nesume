"""유예 중(삭제 예약) 계정 차단 의존성 (B20, part2_guide 4.49).

D7 인증 의존성에 연결해 쓴다. 삭제 예약 중인 계정이면 403 `account_deletion_pending`.
철회 API(`cancel_account_deletion`을 부르는 엔드포인트)에는 붙이지 않는다.
Cognito 비활성화로 새 로그인은 이미 막히고, 이 의존성은 남아 있는 토큰(최대 만료 시각까지)을 막는다.
"""
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser, CurrentUser
from app.core.errors import ForbiddenError
from app.db import get_db
from app.features.deletion.service import deletion_pending

PENDING_MESSAGE = "삭제 예정인 계정입니다. 30일 안에 철회하면 다시 이용할 수 있습니다."


def require_active_account(user: AuthenticatedUser, db: Annotated[Session, Depends(get_db)]) -> CurrentUser:
    if deletion_pending(db, user.sub):
        raise ForbiddenError(PENDING_MESSAGE, code="account_deletion_pending")
    return user
