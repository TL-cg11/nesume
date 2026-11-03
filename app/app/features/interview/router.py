"""B13 모의 면접 API. 자소서 라우터 아래(/resumes/{id}/interviews/...)에 붙어 main.py 등록 없이 동작한다.

LLM을 부르는 엔드포인트(시작·답변·종료·피드백)는 요청 단위 DB 세션(get_db)을 쓰지 않는다.
읽기·쓰기만 짧은 세션으로 열고 모델을 기다리는 동안은 커넥션을 잡지 않는다(A11 matching과 같은 이유).
A12 멀티턴 방어가 대화를 이어 보도록, 세션 헤더가 없으면 면접 ID로 세션을 묶는다.
"""
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

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
Interactive = Annotated[CurrentUser, Depends(require_interactive)]  # 대화형 LLM: 시스템 계정 차단(D7)
Guard = Annotated[Guardrail, Depends(get_guardrail)]
SessionHeader = Annotated[str | None, Depends(session_header)]

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
_EMPTY = "면접을 시작할 내용이 없습니다. 자소서 문항에 내용을 저장한 뒤 다시 시도해 주세요."
_SENSITIVE = "주민번호·계좌번호 등 민감정보는 입력할 수 없습니다. 해당 내용을 지우고 다시 시도해 주세요."
_NO_REPLY = "면접관이 답하지 못했습니다. 잠시 후 다시 보내 주세요."
_NOT_ACTIVE = "이미 끝난 면접입니다."
_CONFLICT = "답변이 동시에 들어왔습니다. 화면을 새로 고친 뒤 다시 시도해 주세요."
_NO_ANSWERS = "답변이 없어 피드백할 내용이 없습니다."


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    main_count: int = Field(default=service.MAIN_DEFAULT, ge=service.MAIN_MIN, le=service.MAIN_MAX)


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=service.ANSWER_MAX)


class MessageOut(BaseModel):
    id: uuid.UUID
    seq: int
    role: str  # interviewer / candidate
    kind: str | None  # main / follow_up / closing (면접관만)
    body: str
    created_at: datetime


class SessionOut(BaseModel):
    id: uuid.UUID
    resume_id: uuid.UUID
    status: str  # active / finished
    main_count: int
    main_no: int
    follow_used: int
    answers: int
    persona: str | None  # 끝난 뒤에만
    persona_label: str | None
    messages: list[MessageOut]
    feedback: dict[str, str] | None  # 구조·구체성·일관성·질문별·제안. 끝난 뒤, 모델을 못 불렀으면 None
    expected_questions: list[str]  # 끝난 뒤 피드백과 함께
    created_at: datetime
    finished_at: datetime | None


class SessionSummary(BaseModel):
    id: uuid.UUID
    status: str
    main_count: int
    answers: int
    persona_label: str | None
    has_feedback: bool
    created_at: datetime
    finished_at: datetime | None


class TurnOut(BaseModel):
    session: SessionOut | None  # 모델 없음·차단으로 시작하지 못했으면 None
    llm_unavailable: bool = False
    blocked_reason: str | None = None


def _in_session[T](fn: Callable[[Session], T]) -> Callable[[], T]:
    """짧은 세션 하나로 fn을 실행하고 커밋한다(스레드풀에서 부른다)."""
    from app.db import SessionLocal

    def run() -> T:
        with SessionLocal.begin() as db:
            return fn(db)
    return run


async def _db[T](fn: Callable[[Session], T]) -> T:
    try:
        return await run_in_threadpool(_in_session(fn))
    except service.NotFound:
        raise _NOT_FOUND from None
    except service.NotActive:
        raise HTTPException(status.HTTP_409_CONFLICT, _NOT_ACTIVE) from None
    except service.Conflict:
        raise HTTPException(status.HTTP_409_CONFLICT, _CONFLICT) from None


def _ctx(user: CurrentUser, header: str | None, interview_id: uuid.UUID):
    kw = guardrail_kwargs(user, header or f"interview-{interview_id}")
    return service.make_ctx(kw["user_id"], kw["role"], kw["session_id"], kw["is_test"], kw["request_id"])


async def _view(owner: str, resume_id: uuid.UUID, sid: uuid.UUID) -> dict:
    return await _db(lambda db: service.session_view(db, owner, resume_id, sid))


async def _give_feedback(guard: Guardrail, ctx, owner: str, resume_id: uuid.UUID, sid: uuid.UUID) -> TurnOut:
    """끝난 면접의 피드백·예상 질문을 만든다. 모델을 못 부르면 면접만 끝난 상태로 돌려준다(다시 받기 가능)."""
    t = await _db(lambda db: service.load_feedback(db, owner, resume_id, sid))
    got = await service.ask_feedback(guard, ctx, t)
    if isinstance(got, service.Outcome):
        return TurnOut(session=await _view(owner, resume_id, sid), llm_unavailable=got.llm_unavailable,
                       blocked_reason=got.blocked_reason)
    feedback, expected = got
    try:
        await _db(lambda db: service.save_feedback(db, owner, resume_id, sid, feedback, expected))
    except pii_hooks.SensitiveInputBlocked:  # 모델이 민감정보를 만들어 낸 경우 — 저장하지 않는다
        return TurnOut(session=await _view(owner, resume_id, sid), blocked_reason="sensitive_output")
    return TurnOut(session=await _view(owner, resume_id, sid))


@router.get("/{resume_id}/interviews", response_model=list[SessionSummary])
def list_sessions(resume_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    try:
        return service.list_sessions(db, user.sub, resume_id)
    except service.NotFound:
        raise _NOT_FOUND from None


@router.post("/{resume_id}/interviews", response_model=TurnOut, status_code=status.HTTP_201_CREATED)
async def start(resume_id: uuid.UUID, payload: StartIn, user: Interactive, guard: Guard,
                header: SessionHeader = None):
    owner, sid = user.sub, uuid.uuid4()
    ctx = _ctx(user, header, sid)
    try:
        t = await _db(lambda db: service.load_start(db, owner, resume_id))
    except service.NothingToAsk:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _EMPTY) from None
    got = await service.ask_opening(guard, ctx, t, payload.main_count)
    if isinstance(got, service.Outcome):
        return TurnOut(session=None, llm_unavailable=got.llm_unavailable, blocked_reason=got.blocked_reason)
    if not got:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _NO_REPLY)
    try:
        await _db(lambda db: service.create_session(db, owner, resume_id, sid, t, payload.main_count, got))
    except pii_hooks.SensitiveInputBlocked:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _NO_REPLY) from None
    return TurnOut(session=await _view(owner, resume_id, sid))


@router.get("/{resume_id}/interviews/{session_id}", response_model=SessionOut)
def get_session(resume_id: uuid.UUID, session_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    try:
        return service.session_view(db, user.sub, resume_id, session_id)
    except service.NotFound:
        raise _NOT_FOUND from None


@router.delete("/{resume_id}/interviews/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(resume_id: uuid.UUID, session_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    try:
        service.delete_session(db, user.sub, resume_id, session_id)
    except service.NotFound:
        raise _NOT_FOUND from None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{resume_id}/interviews/{session_id}/answers", response_model=TurnOut)
async def answer(resume_id: uuid.UUID, session_id: uuid.UUID, payload: AnswerIn, user: Interactive,
                 guard: Guard, header: SessionHeader = None):
    owner, text = user.sub, payload.answer.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "답변을 입력해 주세요.")
    try:
        pii_hooks.ensure_no_sensitive(text)  # spec 3.3: 답변 입력에도 민감정보 차단(모델에 보내기 전)
    except pii_hooks.SensitiveInputBlocked:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _SENSITIVE) from None
    ctx = _ctx(user, header, session_id)
    t = await _db(lambda db: service.load_turn(db, owner, resume_id, session_id, text))
    got = await service.ask_next(guard, ctx, t)
    if isinstance(got, service.Outcome):  # 이번 턴은 저장하지 않는다 — 같은 답변을 다시 보내면 된다
        return TurnOut(session=await _view(owner, resume_id, session_id), llm_unavailable=got.llm_unavailable,
                       blocked_reason=got.blocked_reason)
    kind, reply = got
    if kind != "closing" and not reply:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _NO_REPLY)
    try:
        finished = await _db(lambda db: service.save_turn(db, owner, resume_id, session_id, t.next_seq, text,
                                                          kind, reply))
    except pii_hooks.SensitiveInputBlocked:  # 면접관 말에 민감정보가 섞인 경우 — 저장하지 않는다
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _NO_REPLY) from None
    if finished:
        return await _give_feedback(guard, ctx, owner, resume_id, session_id)
    return TurnOut(session=await _view(owner, resume_id, session_id))


@router.post("/{resume_id}/interviews/{session_id}/finish", response_model=TurnOut)
async def finish(resume_id: uuid.UUID, session_id: uuid.UUID, user: Interactive, guard: Guard,
                 header: SessionHeader = None):
    """사용자가 면접을 끝낸다. 답변이 있었으면 바로 피드백, 없으면 끝내기만."""
    owner = user.sub
    answered = await _db(lambda db: service.finish(db, owner, resume_id, session_id))
    if not answered:
        return TurnOut(session=await _view(owner, resume_id, session_id))
    return await _give_feedback(guard, _ctx(user, header, session_id), owner, resume_id, session_id)


@router.post("/{resume_id}/interviews/{session_id}/feedback", response_model=TurnOut)
async def feedback(resume_id: uuid.UUID, session_id: uuid.UUID, user: Interactive, guard: Guard,
                   header: SessionHeader = None):
    """끝난 면접의 피드백을 (다시) 받는다 — 종료 때 모델을 못 불렀을 때."""
    try:
        return await _give_feedback(guard, _ctx(user, header, session_id), user.sub, resume_id, session_id)
    except service.NoAnswers:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _NO_ANSWERS) from None
