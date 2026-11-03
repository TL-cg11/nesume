"""GitHub 프로젝트 소개 API (tasks B14).

경험 라우터 아래(/experiences/github)에 붙어 main.py 등록 없이 동작한다.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth import CurrentUser, require_interactive
from app.core.errors import AppError
from app.features.github import client, service
from app.guardrail import Guardrail
from app.guardrail.fastapi import get_guardrail, guardrail_kwargs, session_header

router = APIRouter(prefix="/github", tags=["github"])

_BAD_URL = "https://github.com/소유자/저장소 형식의 공개 저장소 주소를 입력해 주세요."
_NOT_FOUND = "저장소를 찾을 수 없습니다. 공개 저장소만 지원합니다."
_RATE_LIMITED = "GitHub 조회 한도를 넘었습니다. 잠시 후 다시 시도해 주세요."
_UNAVAILABLE = "GitHub에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."


Tech = Annotated[str, Field(min_length=1, max_length=50)]


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_url: str = Field(min_length=1, max_length=300)
    role: str = Field(default="", max_length=200)  # 강조할 역할
    tech: list[Tech] = Field(default_factory=list, max_length=10)


class Language(BaseModel):
    name: str
    percent: int


class RepoOut(BaseModel):
    full_name: str
    html_url: str
    description: str
    languages: list[Language]
    commits: int
    contributors: int


class DraftOut(BaseModel):
    repo: RepoOut
    sections: dict[str, str]  # 배경·역할·기술·성과
    questions: list[str]       # README가 없거나 짧을 때 보완 질문
    readme_used: bool
    readme_flags: list[str]    # C5 전처리 탐지 신호
    llm_used: bool
    llm_unavailable: bool
    blocked_reason: str | None
    experience_draft: dict     # B5 POST /experiences 에 그대로 보낼 값(화면에서 수정)


@router.post("/draft", response_model=DraftOut)
async def draft(
    payload: DraftRequest,
    user: Annotated[CurrentUser, Depends(require_interactive)],  # 대화형 LLM: 시스템 계정 차단(D7)
    guard: Annotated[Guardrail, Depends(get_guardrail)],
    session_id: Annotated[str | None, Depends(session_header)] = None,
):
    kw = guardrail_kwargs(user, session_id)
    try:
        res = await service.draft(payload.repo_url, role=payload.role.strip(), tech=payload.tech, guard=guard,
                                  user_id=kw["user_id"], user_role=kw["role"], session_id=kw["session_id"],
                                  is_test=kw["is_test"], request_id=kw["request_id"])
    except client.InvalidRepoUrl:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _BAD_URL) from None
    except client.RepoNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND) from None
    except client.RateLimited:
        raise AppError(_RATE_LIMITED, code="github_rate_limited", status_code=429) from None
    except client.GithubUnavailable:
        raise AppError(_UNAVAILABLE, code="github_unavailable", status_code=503) from None
    return res.__dict__
