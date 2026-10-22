"""A13 API 스키마.

★ 저장하지 않는다. 글을 받아 측정·제안을 돌려주고, 수락한 제안을 반영해 돌려줄 뿐이다.
  버전 저장은 B4 경로(`resumes.service.create_version`)를 쓸 예정이며, `source` 값 규약은
  A7 과 함께 B 와 협의 중이다 (2026-10-22).

★ **사용자가 보는 원문**을 받는다. 저장된 본문(`versions.body`)은 PII 토큰화 상태라
  글자 수가 틀어진다 — `counter` 가 토큰을 발견하면 거절한다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.features.style.counter import CharCount
from app.features.style.length import Trim
from app.features.style.service import AdjustResult, Rewrite
from app.features.style.tone import TONE_NAMES, TONES, ToneAnalysis

#: 한 번에 다룰 수 있는 글자 수. A7·A11 과 같은 값이다.
MAX_TEXT_LEN = 8000

#: 한 번에 받을 수 있는 제안 개수.
MAX_TRIMS = 200


class CountOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: B4 기준 — 이 값이 저장될 `versions.char_count` 가 된다
    total: int
    without_spaces: int

    @classmethod
    def of(cls, c: CharCount) -> CountOut:
        return cls(total=c.total, without_spaces=c.without_spaces)


class SentenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    start: int
    end: int
    tone: str | None
    tone_name: str | None


class ToneOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    main: str | None
    main_name: str | None
    is_mixed: bool
    counts: dict[str, int]
    #: 목표 문체가 아닌 문장만. 화면에서 이 문장을 짚어 준다
    off_tone: list[SentenceOut]

    @classmethod
    def of(cls, a: ToneAnalysis, target: str) -> ToneOut:
        return cls(
            main=a.main,
            main_name=TONE_NAMES[a.main] if a.main else None,
            is_mixed=a.is_mixed,
            counts={k: v for k, v in a.counts.items() if v},
            off_tone=[
                SentenceOut(
                    text=s.text, start=s.start, end=s.end,
                    tone=s.tone, tone_name=TONE_NAMES[s.tone] if s.tone else None,
                )
                for s in a.off_tone(target)  # type: ignore[arg-type]
            ],
        )


class TrimOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    rule_id: str
    start: int
    end: int
    original: str
    replacement: str
    saved: int
    reason: str
    confidence: str

    @classmethod
    def of(cls, t: Trim) -> TrimOut:
        return cls(
            id=t.id, rule_id=t.rule_id, start=t.start, end=t.end,
            original=t.original, replacement=t.replacement, saved=t.saved,
            reason=t.reason, confidence=t.confidence,
        )

    def to_domain(self) -> Trim:
        return Trim(
            rule_id=self.rule_id, start=self.start, end=self.end,
            original=self.original, replacement=self.replacement,
            reason=self.reason, confidence=self.confidence,  # type: ignore[arg-type]
        )


class RewriteOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    count: CountOut
    tone: str | None
    confidence: str

    @classmethod
    def of(cls, r: Rewrite) -> RewriteOut:
        return cls(
            text=r.text, count=CountOut.of(r.count),
            tone=r.tone, confidence=r.confidence,
        )


class AdjustRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TEXT_LEN)
    #: 문항의 글자 수 상한 (`questions.char_limit`). 없으면 길이는 보지 않는다
    limit: int | None = Field(default=None, gt=0)
    #: 최소 분량. 미치면 **질문만** 돌려준다 — 채워 주면 없는 경험을 지어낸다
    min_chars: int | None = Field(default=None, gt=0)
    target_tone: str = Field(default="formal")
    use_llm: bool = True

    @model_validator(mode="after")
    def _check(self) -> AdjustRequest:
        if self.target_tone not in TONES:
            raise ValueError(f"target_tone 은 {list(TONES)} 중 하나여야 합니다")
        if self.limit is not None and self.min_chars is not None and self.min_chars > self.limit:
            raise ValueError("min_chars 가 limit 보다 클 수 없습니다")
        return self


class AdjustResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: CountOut
    fits: bool
    over_by: int
    tone: ToneOut
    trims: list[TrimOut]
    #: 제안을 전부 수락했을 때의 글자 수
    rule_count: CountOut | None
    rule_only_fits: bool
    #: 모델이 다시 쓴 글. 검증을 통과한 것만 담긴다
    rewrite: RewriteOut | None
    #: 모델 결과를 버린 이유 — 그대로 보여준다
    rejected_reason: str | None
    #: 분량이 모자랄 때의 질문
    questions: list[str]
    notice: str
    attempts: int
    llm_used: bool
    llm_unavailable: bool
    blocked_reason: str | None
    counts: dict[str, int]

    @classmethod
    def of(cls, r: AdjustResult, *, notice: str) -> AdjustResponse:
        return cls(
            count=CountOut.of(r.count),
            fits=r.fits,
            over_by=r.count.over_by(r.target_limit),
            tone=ToneOut.of(r.tone, r.target_tone),
            trims=[TrimOut.of(t) for t in r.trims],
            rule_count=CountOut.of(r.rule_count) if r.rule_count else None,
            rule_only_fits=r.rule_only_fits,
            rewrite=RewriteOut.of(r.rewrite) if r.rewrite else None,
            rejected_reason=r.rejected_reason,
            questions=list(r.questions),
            notice=notice,
            attempts=r.attempts,
            llm_used=r.llm_used,
            llm_unavailable=r.llm_unavailable,
            blocked_reason=r.blocked_reason,
            counts=r.counts,
        )


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TEXT_LEN)
    trims: list[TrimOut] = Field(default_factory=list, max_length=MAX_TRIMS)
    accepted: list[str] = Field(default_factory=list, max_length=MAX_TRIMS)


class ApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    applied: int
    count: CountOut
