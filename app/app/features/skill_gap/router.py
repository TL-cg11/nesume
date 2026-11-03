"""C10 — 맞춤 학습 갭 API: 자소서 1건 + 공고 1건 → 배워야 할 역량(중요도순).

`POST /learning-gaps {resume_id, posting_id}`
  자소서 본문 + 본인 경험(B 창구) ↔ 공고 요건(A11 규칙 추출, LLM 없음) → 3종 분류(`classify`)
  → 기술 역량 갭·직무 역량 갭(missing만, 필수·우대) + 지원 조건(참고) + 이미 갖춘 것.
  `gaps`·`domain_gaps`는 C14 `POST /roadmaps`의 `gaps`에 그대로 넣을 수 있는 모양이다.
- 공고는 C4 창구(`get_posting_fields`, 권한 포함), A11과 같은 손질(`prepare_posting`: A1 mask → C5 전처리).
- 자소서 원문은 서버 안에서만 쓰고 응답에 싣지 않는다(근거 필드는 **공고 쪽** 필드명만).
- 본인 자소서·볼 수 있는 공고만 — 아니면 404(없음과 구분 안 함).
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.db import get_db
from app.features.matching.coverage import compare
from app.features.matching.keywords import PostingFields, extract
from app.features.matching.service import prepare_posting
from app.features.matching.vocab import squash
from app.features.skill_gap.classify import CONDITION, DOMAIN, SKILL, kind_of, tidy
from app.features.skill_gap.evidence import gather_evidence
from app.features.skill_gap.gap import from_coverage, learning_gaps
from app.postings.read import get_posting_fields, get_recruit_fields, narrow_to_field

router = APIRouter(prefix="/learning-gaps", tags=["learning-gaps"])
Db = Annotated[Session, Depends(get_db)]


class LearningGapsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resume_id: uuid.UUID
    posting_id: uuid.UUID
    #: 모집분야가 여럿인 공고에서 **그 분야 글로만** 분석(추천이 준 "맞는 분야" 순번). 없으면 공고 전체
    field_index: int | None = Field(default=None, ge=0, le=50)


class GapOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str
    importance: str
    evidence_fields: list[str]


class ConditionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    #: 병역 / 학력 / 경력 / 전공 / 결격 / 인적사항 / 근무조건
    kind: str
    importance: str


class CoveredOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    #: skill(사전 기술) / domain(직무 역량)
    kind: str
    #: covered = 자소서에 있음 / in_experience_only = 경험에만 있음
    status: str
    #: 근거가 된 경험 이름(경험 제목만 — 본문은 싣지 않음)
    experiences: list[str]


class LearningGapsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: **기술 역량** 중 부족한 것(사전 기술, 필수·우대, 중요도순) — 로드맵 기본 포함
    gaps: list[GapOut]
    #: **직무 역량** 중 부족한 것(사전 밖 — IFRS17 등). 사용자가 고르면 로드맵에(강좌 매칭은 약할 수 있음)
    domain_gaps: list[GapOut]
    #: **지원 조건**(병역·학력·경력 연수 등) — 배울 대상이 아니라 참고로만
    conditions: list[ConditionOut]
    #: 이미 갖춘 역량(기술·직무) — 자소서에 있는지, 경험에만 있는지
    covered: list[CoveredOut]
    #: 대조 상태별 개수(covered / in_experience_only / missing)
    counts: dict[str, int]


@router.post("", response_model=LearningGapsOut)
def learning_gaps_for(payload: LearningGapsRequest, user: AuthenticatedUser, db: Db):
    evidence = gather_evidence(db, owner_id=user.sub, resume_id=payload.resume_id)
    fields = get_posting_fields(db, payload.posting_id, user_id=user.sub)
    if evidence is None or fields is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "자소서 또는 공고를 찾을 수 없습니다")
    if payload.field_index is not None:
        recruit = get_recruit_fields(db, payload.posting_id, user_id=user.sub)
        fields = narrow_to_field(fields, recruit, payload.field_index)
    prepared = prepare_posting(PostingFields(**fields))
    report = compare(tuple(extract(prepared.fields)), evidence)

    # 요건마다 종류(기술/직무/조건/잡음)를 붙인다 — from_coverage와 report.matches는 같은 순서
    flat = from_coverage(report.matches)
    # 원문 줄 문맥(전공 목록)은 좁힌 분야 글로 본다
    kinds = [kind_of(m.keyword.text, m.keyword.category, fields) for m in report.matches]
    by_kind = {SKILL: [], DOMAIN: []}
    conditions, covered = [], []
    for m, f, (kind, cond) in zip(report.matches, flat, kinds, strict=True):
        if kind == CONDITION:
            conditions.append(ConditionOut(label=f.label, kind=cond, importance=f.importance))
        elif kind in by_kind:
            if kind == DOMAIN:  # 잘린 조각을 다듬은 말로 보이고, 키도 그 말로(같은 말은 하나로 합쳐짐)
                label = tidy(f.label)
                f = replace(f, label=label, key=squash(label))
            by_kind[kind].append(f)
            if f.status != "missing":
                covered.append(
                    CoveredOut(label=f.label, kind=kind, status=f.status, experiences=list(m.experiences))
                )

    def _out(gaps):
        # 같은 키는 한 번만(중요도순 정렬이라 첫 것이 가장 중요한 것)
        seen: set[str] = set()
        return [
            GapOut(key=g.key, label=g.label, importance=g.importance, evidence_fields=list(g.evidence_fields))
            for g in gaps
            if not (g.key in seen or seen.add(g.key))
        ]

    return LearningGapsOut(
        gaps=_out(learning_gaps(by_kind[SKILL])),
        domain_gaps=_out(learning_gaps(by_kind[DOMAIN])),
        conditions=list({c.label: c for c in conditions}.values()),
        covered=list({c.label: c for c in covered}.values()),
        counts=report.counts(),
    )
