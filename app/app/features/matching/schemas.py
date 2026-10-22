"""A11 API 스키마.

★ 저장하지 않는다. 공고와 글을 받아 분석 결과를 돌려줄 뿐이다.

공고는 두 가지 방법으로 받는다.

    posting      화면이 이미 들고 있는 값을 그대로 보낸다
    posting_id   C4 가 연 창구(`postings.read.get_posting_fields`)로 읽는다

★ **공고를 읽는 창구는 C 가 하나만 연다** (C 답변 2026-10-22).
  제가 `job_postings` 를 직접 읽으면 **접근 통제·조회 로직이 두 곳으로 갈라진다**
  (A8 의 C6 어댑터와 같은 문제). 그래서 A 는 그 함수만 부르고 `JobPosting` ORM 은
  모른다 — C4 가 컬럼을 바꿔도 그 함수 한 곳만 고치면 된다.

★ 경험·자소서(B 소유)는 **아직 호출자가 넘긴다.** B 답변을 기다리는 중이다.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.features.matching.coverage import ExperienceRef, Match, UserEvidence
from app.features.matching.keywords import PostingFields
from app.features.matching.service import Hint

#: 자소서 본문 상한. A7 과 같은 값이다(자소서 문항 하나가 보통 1,000~2,000자).
MAX_TEXT_LEN = 8000

#: 공고 필드 하나의 상한. C5 전처리의 기본 상한과 같다.
MAX_FIELD_LEN = 8000

#: 한 번에 보낼 수 있는 경험 개수·태그 개수. 없으면 입력 하나로 정규식 시간이 늘어난다.
MAX_EXPERIENCES = 30
MAX_TERMS = 40


class PostingIn(BaseModel):
    """공고에서 A11 이 보는 필드만. 이름은 C4 모델과 같게 두었다."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=MAX_FIELD_LEN)
    job_name: str | None = Field(default=None, max_length=MAX_FIELD_LEN)
    job_content: str | None = Field(default=None, max_length=MAX_FIELD_LEN)
    certificates: str | None = Field(default=None, max_length=MAX_FIELD_LEN)
    preferred: str | None = Field(default=None, max_length=MAX_FIELD_LEN)
    major: str | None = Field(default=None, max_length=MAX_FIELD_LEN)
    computer_skills: str | None = Field(default=None, max_length=MAX_FIELD_LEN)

    @model_validator(mode="after")
    def _not_all_empty(self) -> PostingIn:
        if not self.to_domain().texts():
            raise ValueError("공고 필드가 모두 비어 있습니다")
        return self

    def to_domain(self) -> PostingFields:
        return PostingFields(
            title=self.title, job_name=self.job_name, job_content=self.job_content,
            certificates=self.certificates, preferred=self.preferred,
            major=self.major, computer_skills=self.computer_skills,
        )


class ExperienceIn(BaseModel):
    """경험 하나. `label` 은 화면에 보여줄 이름이라 비어 있으면 안 된다."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    text: str = Field(default="", max_length=MAX_TEXT_LEN)
    #: tech_stack + tags 를 합쳐 보낸다
    terms: list[str] = Field(default_factory=list, max_length=MAX_TERMS)

    def to_domain(self) -> ExperienceRef:
        return ExperienceRef(label=self.label, text=self.text, terms=tuple(self.terms))


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: 공고 값을 직접 보내는 경우
    posting: PostingIn | None = None
    #: 저장된 공고를 쓰는 경우. C4 창구로 읽는다
    posting_id: uuid.UUID | None = None
    #: 지금 쓰고 있는 자소서 본문. 비워도 된다 — 쓰기 전에 요건부터 보는 경우가 있다
    resume_text: str = Field(default="", max_length=MAX_TEXT_LEN)
    experiences: list[ExperienceIn] = Field(default_factory=list, max_length=MAX_EXPERIENCES)
    #: false 면 규칙 결과만 돌려준다
    use_llm: bool = True

    @model_validator(mode="after")
    def _exactly_one_posting_source(self) -> AnalyzeRequest:
        """``posting`` 과 ``posting_id`` 중 **하나만** 받는다.

        둘 다 받으면 어느 쪽이 이기는지 호출자가 알 수 없다 — 화면에서 고친 값을
        보냈는데 저장된 원본으로 분석되면 결과가 조용히 달라진다.
        """
        if (self.posting is None) == (self.posting_id is None):
            raise ValueError("posting 과 posting_id 중 하나만 보내야 합니다")
        return self

    def evidence(self) -> UserEvidence:
        return UserEvidence(
            resume_text=self.resume_text,
            experiences=tuple(e.to_domain() for e in self.experiences),
        )


class MatchOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    importance: str
    category: str
    status: str
    #: 어느 공고 필드에서 나온 요건인지 — 사용자에게 근거로 보여준다
    fields: list[str]
    #: 근거가 된 경험 이름
    experiences: list[str]
    #: 택일 묶음 이름. 같은 값끼리 하나만 맞아도 충족 — 화면에서 "택일" 로 보여준다
    group: str | None

    @classmethod
    def of(cls, m: Match) -> MatchOut:
        return cls(
            text=m.keyword.text,
            importance=m.keyword.importance,
            category=m.keyword.category,
            status=m.status,
            fields=list(m.keyword.fields),
            experiences=list(m.experiences),
            group=m.keyword.group,
        )


class HintOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str
    sentence: str
    experiences: list[str]
    confidence: str

    @classmethod
    def of(cls, h: Hint) -> HintOut:
        return cls(
            keyword=h.keyword, sentence=h.sentence,
            experiences=list(h.experiences), confidence=h.confidence,
        )


class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matches: list[MatchOut]
    #: 빠진 요건에 대한 **질문**. 문장 제안이 아니다
    questions: list[str]
    #: 질문 목록 위에 반드시 함께 보여줄 안내
    notice: str
    #: 경험엔 있는데 자소서에 안 쓴 요건을 넣을 문장 (LLM)
    hints: list[HintOut]
    counts: dict[str, int]
    #: 필수 요건 중 자소서에 쓴 비율. 필수 요건이 없으면 null
    required_rate: float | None
    #: 비율을 믿을 만한가. 키워드가 적으면 false — 화면에서 숫자를 감춘다
    rate_reliable: bool
    #: C5 가 공고에서 찾은 인젝션 신호
    posting_flags: list[str]
    posting_truncated: bool
    llm_used: bool
    llm_unavailable: bool
    blocked_reason: str | None
    #: 모델이 없는 사실을 넣어 버린 문장 수
    dropped_hints: int
