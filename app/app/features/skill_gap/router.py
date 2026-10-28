"""C10 — 맞춤 학습 갭 API: 자소서 1건 + 공고 1건 → 배워야 할 역량(중요도순).

`POST /learning-gaps {resume_id, posting_id}`
  자소서 본문 + 본인 경험(B 창구) ↔ 공고 요건(A11 규칙 추출, LLM 없음) → C10 `learning_gaps`(missing만).
  결과 `gaps`는 C14 `POST /roadmaps`의 `gaps`에 그대로 넣을 수 있는 모양이다.
- 공고는 C4 창구(`get_posting_fields`, 권한 포함), A11과 같은 손질(`prepare_posting`: A1 mask → C5 전처리).
- 자소서 원문은 서버 안에서만 쓰고 응답에 싣지 않는다(근거 필드는 **공고 쪽** 필드명만).
- 본인 자소서·볼 수 있는 공고만 — 아니면 404(없음과 구분 안 함).
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.db import get_db
from app.features.matching.coverage import compare
from app.features.matching.keywords import PostingFields, extract
from app.features.matching.service import prepare_posting
from app.features.skill_gap.evidence import gather_evidence
from app.features.skill_gap.gap import from_coverage, learning_gaps
from app.postings.read import get_posting_fields

router = APIRouter(prefix="/learning-gaps", tags=["learning-gaps"])
Db = Annotated[Session, Depends(get_db)]


class LearningGapsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resume_id: uuid.UUID
    posting_id: uuid.UUID


class GapOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str
    importance: str
    evidence_fields: list[str]


class LearningGapsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: 배워야 할 역량(missing, 필수·우대, 중요도순) — C14 `POST /roadmaps` gaps 입력
    gaps: list[GapOut]
    #: 대조 상태별 개수(covered / in_experience_only / missing) — "이미 갖춘 것" 표시용
    counts: dict[str, int]


@router.post("", response_model=LearningGapsOut)
def learning_gaps_for(payload: LearningGapsRequest, user: AuthenticatedUser, db: Db):
    evidence = gather_evidence(db, owner_id=user.sub, resume_id=payload.resume_id)
    fields = get_posting_fields(db, payload.posting_id, user_id=user.sub)
    if evidence is None or fields is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "자소서 또는 공고를 찾을 수 없습니다")
    prepared = prepare_posting(PostingFields(**fields))
    report = compare(tuple(extract(prepared.fields)), evidence)
    gaps = learning_gaps(from_coverage(report.matches))
    return LearningGapsOut(
        gaps=[
            GapOut(key=g.key, label=g.label, importance=g.importance, evidence_fields=list(g.evidence_fields))
            for g in gaps
        ],
        counts=report.counts(),
    )
