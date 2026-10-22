"""A11 API 스키마.

★ 저장하지 않는다. 공고와 글을 받아 분석 결과를 돌려줄 뿐이다.

★ **공고를 `posting_id` 로 받지 않는다** (2026-10-22 현재).
  공고 조회는 C4 의 `job_postings` 를 읽는 일이고, 경험·자소서 조회는 B 의 테이블을
  읽는 일이다. 양쪽 모두 남의 소유 경로라, 어느 함수로 읽을지 협의되기 전에
  제가 SQL 을 쓰면 **접근 통제가 두 곳으로 갈라진다** (C6 가 역할 필터를 강제하는데
  제가 뒤에서 또 조회하면 그쪽엔 필터가 없다).
  그래서 1차는 **화면이 이미 들고 있는 값을 보내는 방식**으로 만들었다.
"""

from __future__ import annotations

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

    posting: PostingIn
    #: 지금 쓰고 있는 자소서 본문. 비워도 된다 — 쓰기 전에 요건부터 보는 경우가 있다
    resume_text: str = Field(default="", max_length=MAX_TEXT_LEN)
    experiences: list[ExperienceIn] = Field(default_factory=list, max_length=MAX_EXPERIENCES)
    #: false 면 규칙 결과만 돌려준다
    use_llm: bool = True

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
