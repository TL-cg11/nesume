"""A14 프로필 저장소 — 포트와 DB 구현.

★ **소유자 외에는 아무도 읽지 못한다.** 모든 함수가 `owner_id` 를 받고, 그 값으로만
  조회한다. "운영자면 통과" 같은 분기를 두지 않는다 — 분기가 있으면 언젠가 쓰인다.

서비스는 포트만 본다. 그래서 A14 단위 테스트는 **DB 없이** 돈다.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session

from app.features.profile.extract import WritingStyle
from app.models.writing_profile import WritingProfile

#: 화이트리스트 표현을 담는 컬럼 길이(ARRAY(String(20)))에 맞춘 상한.
MAX_TERM_LEN = 20


class ProfileStore(Protocol):
    """말투 프로필 저장소. 모든 호출이 `owner_id` 를 요구한다."""

    def get(self, owner_id: str) -> WritingStyle | None: ...

    def put(self, owner_id: str, style: WritingStyle) -> None: ...

    def delete(self, owner_id: str) -> bool: ...


class InMemoryProfileStore:
    """기본 구현. 테스트와, DB 가 붙기 전 화면 작업에 쓴다."""

    def __init__(self) -> None:
        self._by_owner: dict[str, WritingStyle] = {}

    def get(self, owner_id: str) -> WritingStyle | None:
        return self._by_owner.get(owner_id)

    def put(self, owner_id: str, style: WritingStyle) -> None:
        self._by_owner[owner_id] = style

    def delete(self, owner_id: str) -> bool:
        return self._by_owner.pop(owner_id, None) is not None


def _to_style(row: WritingProfile) -> WritingStyle:
    return WritingStyle(
        avg_sentence_len=row.avg_sentence_len,
        long_sentence_ratio=row.long_sentence_ratio,
        paragraph_avg_sentences=row.paragraph_avg_sentences,
        numeric_density=row.numeric_density,
        endings=tuple(row.endings),
        connectives=tuple(row.connectives),
        source_chars=row.source_chars,
        sentence_count=row.sentence_count,
    )


class DbProfileStore:
    """`writing_profiles` 한 행을 읽고 쓴다.

    사용자당 한 행이라 upsert 다. 등급은 모델 기본값(`personal`)을 쓴다 —
    여기서 다시 지정하지 않는다(지정하면 모델과 어긋날 수 있다).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, owner_id: str) -> WritingStyle | None:
        row = self._session.get(WritingProfile, owner_id)
        return None if row is None else _to_style(row)

    def put(self, owner_id: str, style: WritingStyle) -> None:
        row = self._session.get(WritingProfile, owner_id)
        if row is None:
            row = WritingProfile(owner_id=owner_id)
            self._session.add(row)

        row.avg_sentence_len = style.avg_sentence_len
        row.long_sentence_ratio = style.long_sentence_ratio
        row.paragraph_avg_sentences = style.paragraph_avg_sentences
        row.numeric_density = style.numeric_density
        # 길이 상한을 넘는 표현은 저장하지 않는다. 화이트리스트에서만 오므로
        # 넘을 일이 없지만, 넘으면 DB 오류로 요청이 죽는다
        row.endings = [t for t in style.endings if len(t) <= MAX_TERM_LEN]
        row.connectives = [t for t in style.connectives if len(t) <= MAX_TERM_LEN]
        row.source_chars = style.source_chars
        row.sentence_count = style.sentence_count
        self._session.flush()

    def delete(self, owner_id: str) -> bool:
        row = self._session.get(WritingProfile, owner_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True
