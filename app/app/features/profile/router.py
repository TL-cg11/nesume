"""A14 — 말투 프로필 API (tasks.md A14).

★ **본인만 쓴다. 멘토·운영자도 조회할 수 없다.**
  저장소 함수가 전부 `owner_id` 를 받고 그 값으로만 조회한다. 역할을 보고 통과시키는
  분기를 두지 않았다 — 분기가 있으면 언젠가 쓰인다.

  이것은 `matrix.yaml` 보다 엄격하다(매트릭스는 운영자에게 `personal: mask/all` 을
  준다). 말투 프로필은 **문체 지문**이라 공유된 자소서의 작성자를 역추적하는 데
  쓸 수 있고, **마스킹으로 가릴 수 있는 종류의 값이 아니다.** docs/A14.md 에 적었다.

★ LLM 을 부르지 않는다. 추출은 전부 규칙이다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.db import get_db
from app.features.profile import service
from app.features.profile.extract import NotEnoughText, TokenizedTextError
from app.features.profile.schemas import (
    MAX_TEXT_LEN,
    BuildRequest,
    ProfileOut,
    RequirementOut,
)
from app.features.profile.store import DbProfileStore, ProfileStore

router = APIRouter(prefix="/profile", tags=["profile"])

Db = Annotated[Session, Depends(get_db)]


def get_store(db: Db) -> ProfileStore:
    """테스트에서 갈아끼울 수 있게 의존성으로 뺀다.

    LLM 을 부르지 않아 응답이 짧으므로 요청 단위 세션을 그대로 쓴다
    (A11 은 모델을 기다리는 동안 커넥션을 잡지 않으려고 짧은 세션을 썼다).
    """
    return DbProfileStore(db)


def _out(style: service.WritingStyle) -> ProfileOut:
    thin = service.is_thin(style)
    return ProfileOut.of(
        style,
        thin=thin,
        notice=service.THIN_SAMPLE_NOTICE if thin else None,
        fragment=service.prompt_fragment(style),
    )


@router.put("/writing", response_model=ProfileOut)
def build(
    payload: BuildRequest,
    user: AuthenticatedUser,
    store: ProfileStore = Depends(get_store),
) -> ProfileOut:
    """내가 쓴 글에서 말투를 뽑아 저장한다. 이전 프로필은 **덮어쓴다.**"""
    try:
        style = service.build(payload.text, owner_id=user.sub, store=store)
    except TokenizedTextError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except NotEnoughText as exc:
        # 글이 모자란 것은 오류가 아니라 **조건 미달**이다. 몇 자 더 필요한지 알려준다
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    return _out(style)


@router.get(
    "/writing",
    response_model=ProfileOut,
    responses={404: {"model": RequirementOut}},
)
def read(user: AuthenticatedUser, store: ProfileStore = Depends(get_store)) -> ProfileOut:
    """내 프로필. 없으면 404 와 함께 **무엇이 필요한지**를 돌려준다."""
    style = service.get(user.sub, store=store)
    if style is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"말투 프로필이 없습니다. 쓴 글 {service.MIN_SOURCE_CHARS}자 이상으로 만들 수 있습니다",
        )
    return _out(style)


@router.delete("/writing", status_code=status.HTTP_204_NO_CONTENT)
def remove(user: AuthenticatedUser, store: ProfileStore = Depends(get_store)) -> Response:
    """내 프로필을 지운다.

    ★ 지울 수 있어야 한다. 말투 프로필은 **사용자가 만들라고 한 적 없는 파생 데이터**다
      (B20 삭제 정책과 같은 생각). 없어도 204 로 답한다 — 지워 달라는 요청의 결과는
      "없다" 이고, 그게 이미 참이면 성공이다.
    """
    service.delete(user.sub, store=store)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router", "get_store", "MAX_TEXT_LEN"]
