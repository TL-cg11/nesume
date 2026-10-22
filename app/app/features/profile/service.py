"""A14 조립 — 말투 프로필을 만들고, 프롬프트에 넣을 문단을 만든다.

    PUT    /profile/writing   사용자가 쓴 글(1,000자+) → 프로필 생성·갱신
    GET    /profile/writing   내 프로필
    DELETE /profile/writing   내 프로필 삭제

★ **LLM 을 부르지 않는다.** 말투 추출은 전부 규칙이다. 모델에게 "이 사람 말투를
  요약해 줘" 라고 물으면 **요약문에 원문 조각이 들어오고**, 그것이 프로필로 저장된다.
  규칙으로 뽑으면 화이트리스트 밖의 말은 아예 들어올 수 없다 (`extract` 주석).

★ 프로필은 **쓰는 쪽에서만** 쓴다. 리라이팅(A6)·조정(A13)이 프롬프트에 한 문단을
  넣는다. 프로필 자체가 모델에게 가는 것이 아니라 **지시문으로 바뀌어** 간다.
"""

from __future__ import annotations

from app.features.profile.extract import (
    MIN_SOURCE_CHARS,
    NotEnoughText,
    TokenizedTextError,
    WritingStyle,
    extract,
)
from app.features.profile.store import ProfileStore

#: 프롬프트 문단 머리말. "내용을 바꾸지 말라" 를 **먼저** 적는다 —
#: 문체를 맞추라는 지시가 사실을 바꾸는 허락으로 읽히면 안 된다.
PROMPT_HEADER = (
    "아래는 글쓴이의 평소 문체입니다. **내용과 사실은 그대로 두고** 문체만 맞춰 주십시오."
)

#: 표본이 적은 프로필에 붙는 안내. 화면에서 그대로 보여준다.
THIN_SAMPLE_NOTICE = (
    "글이 많지 않아 말투가 덜 정확할 수 있습니다. 자소서를 더 쓰면 다시 뽑아 보십시오."
)

#: 이 문장 수 아래면 표본이 얇다고 본다. 1,000자를 넘겨도 한 문장이 길면 표본은 적다.
THIN_SENTENCE_COUNT = 15


def build(text: str, *, owner_id: str, store: ProfileStore) -> WritingStyle:
    """글에서 말투를 뽑아 저장한다. 글이 모자라면 `NotEnoughText`.

    ★ **덮어쓴다.** 이전 프로필과 평균을 내지 않는다 — 말투는 바뀌고, 사용자는
      방금 쓴 글을 기준으로 삼기를 기대한다. 합치면 **어느 글이 반영됐는지 알 수 없다.**
    """
    style = extract(text)
    store.put(owner_id, style)
    return style


def get(owner_id: str, *, store: ProfileStore) -> WritingStyle | None:
    """내 프로필. 없으면 None."""
    return store.get(owner_id)


def delete(owner_id: str, *, store: ProfileStore) -> bool:
    """내 프로필을 지운다. 지울 것이 없었으면 False."""
    return store.delete(owner_id)


def is_thin(style: WritingStyle) -> bool:
    """표본이 얇은 프로필인가. 화면에서 안내를 붙일지 정하는 데 쓴다."""
    return style.sentence_count < THIN_SENTENCE_COUNT


def prompt_fragment(style: WritingStyle | None) -> str:
    """리라이팅·조정 프롬프트에 넣을 문단. 프로필이 없으면 **빈 문자열**.

    ★ 없으면 아무것도 넣지 않는다. "문체 정보 없음" 같은 문구를 넣으면 모델이
      그 문장에 반응해 엉뚱한 소리를 한다 — A5 `OutputContext` 를 비워 두면 그 검사만
      건너뛰는 것과 같은 판단이다. **모르는 것을 지시로 만들지 않는다.**
    """
    if style is None:
        return ""

    lines = [
        PROMPT_HEADER,
        f"- 문장은 평균 {style.avg_sentence_len}자 정도로 씁니다.",
        f"- 한 문단에 문장 {style.paragraph_avg_sentences}개 정도를 씁니다.",
    ]
    if style.endings:
        lines.append(f"- 자주 쓰는 문장 끝: {' · '.join(style.endings)}")
    if style.connectives:
        lines.append(f"- 자주 쓰는 연결 표현: {' · '.join(style.connectives)}")
    if style.long_sentence_ratio >= 20:
        lines.append("- 긴 문장을 즐겨 씁니다. 짧게 끊지 마십시오.")
    if style.numeric_density >= 10:
        lines.append("- 성과를 숫자로 적는 편입니다. 있는 숫자를 지우지 마십시오.")

    return "\n".join(lines)


__all__ = [
    "MIN_SOURCE_CHARS",
    "PROMPT_HEADER",
    "THIN_SAMPLE_NOTICE",
    "THIN_SENTENCE_COUNT",
    "NotEnoughText",
    "TokenizedTextError",
    "WritingStyle",
    "build",
    "delete",
    "get",
    "is_thin",
    "prompt_fragment",
]
