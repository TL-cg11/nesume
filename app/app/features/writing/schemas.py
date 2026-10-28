"""A7 API 스키마.

★ 저장하지 않는다. 글을 받아 제안을 돌려주고, 수락한 것을 반영해 돌려줄 뿐이다.
  버전 저장은 B4 경로를 쓸 예정이며 `source` 값 규약을 B와 협의 중이다 (2026-10-22).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.features.style.tone import DEFAULT_TONE
from app.features.writing.rewrite import (
    DEFAULT_LENGTH,
    MAX_KEYWORDS,
    MAX_SELECTION_LEN,
    RewriteOptions,
    normalize_keywords,
)
from app.features.writing.rewrite_service import Candidate, RewriteResult
from app.features.writing.star import ELEMENT_NAMES, StarAnalysis
from app.features.writing.suggestions import Suggestion

#: 한 번에 검사할 수 있는 글자 수.
#: 자소서 문항 하나가 보통 1,000~2,000자다. 여유를 두되 상한은 둔다 —
#: 없으면 긴 입력 하나로 모델 호출 비용과 정규식 시간이 함께 늘어난다.
MAX_TEXT_LEN = 8000


class ProofreadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TEXT_LEN)
    #: false 면 규칙 검사만 한다. 화면에서 입력 중 실시간 검사에 쓴다
    use_llm: bool = True


class SuggestionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    rule_id: str
    start: int
    end: int
    original: str
    suggested: str
    reason: str
    source: str
    confidence: str
    #: 글을 바꾸는 제안인가. false 면 안내만 하는 항목이다
    is_replacement: bool

    @classmethod
    def of(cls, s: Suggestion) -> SuggestionOut:
        return cls(
            id=s.id, kind=s.kind, rule_id=s.rule_id,
            start=s.start, end=s.end,
            original=s.original, suggested=s.suggested, reason=s.reason,
            source=s.source, confidence=s.confidence,
            is_replacement=s.is_replacement,
        )

    def to_domain(self) -> Suggestion:
        return Suggestion(
            kind=self.kind,  # type: ignore[arg-type]
            rule_id=self.rule_id, start=self.start, end=self.end,
            original=self.original, suggested=self.suggested, reason=self.reason,
            source=self.source,  # type: ignore[arg-type]
            confidence=self.confidence,  # type: ignore[arg-type]
        )


class StarOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    present: list[str]
    missing: list[str]
    #: 화면에 보여줄 한글 이름 (상황(Situation) 등)
    missing_names: list[str]
    count: int

    @classmethod
    def of(cls, a: StarAnalysis) -> StarOut:
        return cls(
            present=sorted(a.present),
            missing=list(a.missing),
            missing_names=[ELEMENT_NAMES[e] for e in a.missing],
            count=a.count,
        )


class ProofreadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestions: list[SuggestionOut]
    star: StarOut
    #: 2차(LLM)를 돌렸는가
    llm_used: bool
    #: 모델 제공자가 아직 설정되지 않아 2차를 건너뛰었는가
    llm_unavailable: bool
    #: 가드레일이 모델 응답을 막았으면 그 규칙 ID
    blocked_reason: str | None
    #: 규칙 ID별 개수. 감사·화면 요약용
    counts: dict[str, int]


class ApplyRequest(BaseModel):
    """수락한 제안을 반영한다.

    제안 목록을 함께 받는 이유: LLM 제안은 같은 글에도 다시 만들면 달라질 수 있어
    서버가 재현할 수 없다. 그래서 **받았던 제안을 그대로 돌려받아** 반영한다.
    위치가 아직 맞는지는 서버가 검사한다.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TEXT_LEN)
    suggestions: list[SuggestionOut] = Field(max_length=100)
    accepted: list[str] = Field(max_length=100)


class ApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    applied: int


# --- A6 리라이팅 ---------------------------------------------------------------
#
# ★ 리라이팅은 **고른 구간**을 다룬다. 문항 전체가 아니라 사용자가 에디터에서 드래그한
#   부분이다. 그래서 상한이 A7 보다 크다 — 문항 하나를 통째로 고를 수도 있다.


class RewriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: 에디터에서 고른 구간. 원문 전체가 아니다
    text: str = Field(min_length=1, max_length=MAX_SELECTION_LEN)
    tone: str = Field(default=DEFAULT_TONE)
    length: str = Field(default=DEFAULT_LENGTH)
    keywords: list[str] = Field(default_factory=list, max_length=MAX_KEYWORDS)
    #: false 면 모델을 부르지 않고 지시문만 돌려준다. 화면에서 옵션을 바꿔 보는 데 쓴다
    use_llm: bool = True

    def options(self) -> RewriteOptions:
        """스키마 값을 도메인 옵션으로. 값 검사는 `RewriteOptions` 가 한다 —
        **검사가 한 곳에만 있어야** 화면을 거치지 않는 호출에도 같은 규칙이 선다."""
        return RewriteOptions(
            tone=self.tone,  # type: ignore[arg-type]
            length=self.length,  # type: ignore[arg-type]
            keywords=normalize_keywords(self.keywords),
        )


class DiffSegment(BaseModel):
    """단어 단위 차이 한 조각 (B4 `diff_segments` 와 같은 모양)."""

    model_config = ConfigDict(extra="forbid")

    op: str
    before: str
    after: str


class CandidateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: 후보 번호. 화면이 "후보 2를 저장" 으로 되돌려 보낼 때 쓴다
    index: int
    body: str
    char_count: int
    segments: list[DiffSegment]

    @classmethod
    def of(cls, index: int, c: Candidate) -> CandidateOut:
        return cls(
            index=index,
            body=c.body,
            char_count=len(c.body),
            segments=[DiffSegment(**s) for s in c.segments],
        )


class RewriteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[CandidateOut]
    #: 모델에 간 지시문. A14 와 같은 생각 — 무엇이 갔는지 사용자가 볼 수 있어야 한다
    instructions: str
    #: 나눠 보낸 조각 수. 1 이면 나누지 않았다
    parts: int
    original_char_count: int
    llm_used: bool
    llm_unavailable: bool
    blocked_reason: str | None
    notices: list[str]

    @classmethod
    def of(cls, text: str, r: RewriteResult) -> RewriteResponse:
        return cls(
            candidates=[CandidateOut.of(i + 1, c) for i, c in enumerate(r.candidates)],
            instructions=r.instructions,
            parts=r.parts,
            original_char_count=len(text),
            llm_used=r.llm_used,
            llm_unavailable=r.llm_unavailable,
            blocked_reason=r.blocked_reason,
            notices=list(r.notices),
        )


class RewriteApplyRequest(BaseModel):
    """고른 후보를 새 버전으로 저장한다.

    ★ 본문을 **받아서** 저장한다. 서버가 후보를 다시 만들어 저장할 수는 없다 —
      모델은 같은 입력에도 다른 글을 준다. A7 `ApplyRequest` 가 제안 목록을
      되돌려받는 것과 같은 이유다.
    """

    model_config = ConfigDict(extra="forbid")

    resume_id: uuid.UUID
    question_id: uuid.UUID
    body: str = Field(min_length=1, max_length=MAX_SELECTION_LEN)


class RewriteApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID
    char_count: int
