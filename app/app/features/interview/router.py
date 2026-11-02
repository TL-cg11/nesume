"""B13 면접 연습 API. 자소서 라우터 아래(/resumes/{id}/interview/...)에 붙어 main.py 등록 없이 동작한다.

LLM을 부르는 두 엔드포인트는 요청 단위 DB 세션(get_db)을 쓰지 않는다. 읽기·쓰기만 짧은 세션으로 열고
모델을 기다리는 동안은 커넥션을 잡지 않는다(A11 matching과 같은 이유).
"""
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.auth import AuthenticatedUser, CurrentUser, require_interactive
from app.db import get_db
from app.features.interview import service
from app.features.resumes import pii_hooks
from app.guardrail import Guardrail
from app.guardrail.fastapi import get_guardrail, guardrail_kwargs, session_header

router = APIRouter(tags=["interview"])
Db = Annotated[Session, Depends(get_db)]

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
_EMPTY = "질문을 만들 내용이 없습니다. 자소서 문항에 내용을 저장한 뒤 다시 시도해 주세요."
_SENSITIVE = "주민번호·계좌번호 등 민감정보는 입력할 수 없습니다. 해당 내용을 지우고 다시 시도해 주세요."
_NO_QUESTIONS = "질문을 만들지 못했습니다. 잠시 후 다시 시도해 주세요."


class GenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["personality", "job", "experience"]
    count: int = Field(default=service.COUNT_DEFAULT, ge=service.COUNT_MIN, le=service.COUNT_MAX)


class QuestionOut(BaseModel):
    id: uuid.UUID
    resume_id: uuid.UUID
    type: str
    body: str
    version_ids: list[uuid.UUID]
    answer_count: int
    created_at: datetime


class GenerateOut(BaseModel):
    questions: list[QuestionOut]
    llm_unavailable: bool
    blocked_reason: str | None


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=service.ANSWER_MAX)


class AnswerOut(BaseModel):
    id: uuid.UUID
    question_id: uuid.UUID
    answer: str
    feedback: dict[str, str] | None  # 구조·구체성·일관성·제안. 모델을 못 불렀으면 None
    created_at: datetime


class FeedbackOut(BaseModel):
    answer: AnswerOut | None  # 저장한 연습 기록. 가드레일이 막으면 None(저장 안 함)
    llm_unavailable: bool
    blocked_reason: str | None


def _in_session[T](fn: Callable[[Session], T]) -> Callable[[], T]:
    """짧은 세션 하나로 fn을 실행하고 커밋한다(스레드풀에서 부른다)."""
    from app.db import SessionLocal

    def run() -> T:
        with SessionLocal.begin() as db:
            return fn(db)
    return run


@router.get("/{resume_id}/interview/questions", response_model=list[QuestionOut])
def list_questions(resume_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    try:
        return service.list_questions(db, user.sub, resume_id)
    except service.NotFound:
        raise _NOT_FOUND from None


@router.post("/{resume_id}/interview/questions", response_model=GenerateOut,
             status_code=status.HTTP_201_CREATED)
async def generate(
    resume_id: uuid.UUID,
    payload: GenerateIn,
    user: Annotated[CurrentUser, Depends(require_interactive)],  # 대화형 LLM: 시스템 계정 차단(D7)
    guard: Annotated[Guardrail, Depends(get_guardrail)],
    session_id: Annotated[str | None, Depends(session_header)] = None,
):
    kw = guardrail_kwargs(user, session_id)
    owner = user.sub
    try:
        resume, experiences, used = await run_in_threadpool(
            _in_session(lambda db: service.load_generate_context(db, owner, resume_id)))
    except service.NotFound:
        raise _NOT_FOUND from None
    except service.NothingToAsk:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _EMPTY) from None
    ctx = service._ctx(kw["user_id"], kw["role"], kw["session_id"], kw["is_test"], kw["request_id"])
    got = await service.ask_questions(guard, ctx, type_=payload.type, count=payload.count, resume=resume,
                                      experiences=experiences)
    if isinstance(got, service.GenerateResult):
        return GenerateOut(questions=[], llm_unavailable=got.llm_unavailable,
                           blocked_reason=got.blocked_reason)
    if not got:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _NO_QUESTIONS)
    try:
        saved = await run_in_threadpool(
            _in_session(lambda db: service.save_questions(db, owner, resume_id, payload.type, got, used)))
    except service.NotFound:
        raise _NOT_FOUND from None
    except pii_hooks.SensitiveInputBlocked:  # 모델이 민감정보를 만들어 낸 경우 — 저장하지 않는다
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _NO_QUESTIONS) from None
    return GenerateOut(questions=saved, llm_unavailable=False, blocked_reason=None)


@router.delete("/{resume_id}/interview/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(resume_id: uuid.UUID, question_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    try:
        service.delete_question(db, user.sub, resume_id, question_id)
    except service.NotFound:
        raise _NOT_FOUND from None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{resume_id}/interview/questions/{question_id}/answers", response_model=list[AnswerOut])
def list_answers(resume_id: uuid.UUID, question_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    try:
        return service.list_answers(db, user.sub, resume_id, question_id)
    except service.NotFound:
        raise _NOT_FOUND from None


@router.post("/{resume_id}/interview/questions/{question_id}/answers", response_model=FeedbackOut,
             status_code=status.HTTP_201_CREATED)
async def answer(
    resume_id: uuid.UUID,
    question_id: uuid.UUID,
    payload: AnswerIn,
    user: Annotated[CurrentUser, Depends(require_interactive)],
    guard: Annotated[Guardrail, Depends(get_guardrail)],
    session_id: Annotated[str | None, Depends(session_header)] = None,
):
    kw = guardrail_kwargs(user, session_id)
    owner, text = user.sub, payload.answer.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "답변을 입력해 주세요.")
    try:
        pii_hooks.ensure_no_sensitive(text)  # spec 3.3: 답변 입력에도 민감정보 차단(모델에 보내기 전)
    except pii_hooks.SensitiveInputBlocked:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _SENSITIVE) from None
    try:
        question, resume = await run_in_threadpool(
            _in_session(lambda db: service.load_feedback_context(db, owner, resume_id, question_id)))
    except service.NotFound:
        raise _NOT_FOUND from None
    ctx = service._ctx(kw["user_id"], kw["role"], kw["session_id"], kw["is_test"], kw["request_id"])
    got = await service.ask_feedback(guard, ctx, question=question, answer=text, resume=resume)
    if isinstance(got, service.FeedbackResult):
        return FeedbackOut(answer=None, llm_unavailable=False, blocked_reason=got.blocked_reason)
    try:
        saved = await run_in_threadpool(
            _in_session(lambda db: service.save_answer(db, owner, resume_id, question_id, text, got)))
    except service.NotFound:
        raise _NOT_FOUND from None
    except pii_hooks.SensitiveInputBlocked:  # 피드백에 민감정보가 섞인 경우 — 답변만 기록
        saved = await run_in_threadpool(
            _in_session(lambda db: service.save_answer(db, owner, resume_id, question_id, text, None)))
    return FeedbackOut(answer=saved, llm_unavailable=got is None, blocked_reason=None)
