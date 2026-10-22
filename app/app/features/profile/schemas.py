"""A14 API 스키마.

★ **사용자가 보는 원문**을 받는다. 저장된 본문(`versions.body`)은 PII 토큰화 상태라
  문장 길이가 실제와 달라진다 — `extract` 가 토큰을 발견하면 거절한다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.features.profile.extract import MIN_SOURCE_CHARS, WritingStyle

#: 한 번에 받을 수 있는 글자 수. A7·A11·A13 과 같은 값이다.
MAX_TEXT_LEN = 8000


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: 사용자가 쓴 글. 여러 문항을 이어 붙여 보내도 된다
    text: str = Field(min_length=1, max_length=MAX_TEXT_LEN)


class ProfileOut(BaseModel):
    """★ 여기에 원문 조각은 없다. 문자열 두 필드는 화이트리스트 기능어뿐이다."""

    model_config = ConfigDict(extra="forbid")

    avg_sentence_len: int
    long_sentence_ratio: int
    paragraph_avg_sentences: int
    numeric_density: int
    endings: list[str]
    connectives: list[str]
    source_chars: int
    sentence_count: int
    #: 표본이 얇은가. true 면 화면에서 안내를 함께 보여준다
    thin: bool
    #: 표본이 얇을 때 보여줄 문구. 아니면 null
    notice: str | None
    #: 리라이팅·조정에 들어가는 지시문. 사용자가 **무엇이 모델에 가는지 볼 수 있어야 한다**
    prompt_fragment: str

    @classmethod
    def of(cls, style: WritingStyle, *, thin: bool, notice: str | None, fragment: str) -> ProfileOut:
        return cls(
            avg_sentence_len=style.avg_sentence_len,
            long_sentence_ratio=style.long_sentence_ratio,
            paragraph_avg_sentences=style.paragraph_avg_sentences,
            numeric_density=style.numeric_density,
            endings=list(style.endings),
            connectives=list(style.connectives),
            source_chars=style.source_chars,
            sentence_count=style.sentence_count,
            thin=thin,
            notice=notice,
            prompt_fragment=fragment,
        )


class RequirementOut(BaseModel):
    """프로필이 없을 때 돌려주는 안내."""

    model_config = ConfigDict(extra="forbid")

    min_source_chars: int = MIN_SOURCE_CHARS
    message: str
