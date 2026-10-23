"""말투 프로필 테이블 (A14 소유 모델).

리라이팅(A6)·조정(A13)이 "이 사람처럼" 쓰게 하려고 들고 있는 값이다.

★ **본인만 쓴다. 멘토·운영자도 조회할 수 없다** (`tasks.md` A14).
  등급은 `personal` 이지만 **matrix.yaml 보다 엄격하다** — 매트릭스는 운영자에게
  `personal: {decision: mask, scope: all}` 을 주므로 마스킹 조회가 허용된다.
  A14 는 그 위에 **소유자 외 전면 차단**을 서비스 계층에서 강제한다 (`features/profile`).
  이유: 말투 프로필은 **문체 지문**이라, 공유된 자소서를 보고 누가 썼는지 역추적하는
  데 쓸 수 있다. 마스킹으로 가릴 수 있는 종류의 값이 아니다.
  → 매트릭스에 "소유자 외 전면 차단" 등급이 없다는 점을 D·C 에 알려 두었다 (docs/A14.md).

★ 문자열 컬럼에는 **화이트리스트에서 나온 기능어만** 들어간다(`features/profile/extract.py`).
  자주 쓰는 "표현" 을 그대로 담으면 회사명·학교명·사람 이름이 프로필로 새어 들어온다.

사용자당 한 행이라 `owner_id` 가 기본키다. 사용자 삭제 시 함께 삭제된다(B20).

※ 마이그레이션 번호·`models/__init__.py` 등록은 B 가 취합한다 (`models/posting.py` 와 같은 방식).
"""
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, Grade, UpdatedAt, grade_check, grade_column

#: 상위 표현을 몇 개까지 담는가. 많이 담을수록 **문체 지문이 선명해진다** —
#: A14 추출기의 TOP_N 과 같은 값이어야 한다(테스트로 대조).
MAX_TOP_TERMS = 3


class WritingProfile(Base):
    __tablename__ = "writing_profiles"
    __table_args__ = (grade_check(),)

    #: 사용자당 하나. 사용자 물리 삭제 시 함께 삭제된다
    owner_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    grade: Mapped[str] = grade_column(Grade.PERSONAL)

    # --- 문장 ---
    #: 문장 평균 글자 수
    avg_sentence_len: Mapped[int] = mapped_column(Integer)
    #: 90자를 넘는 문장의 비율 (0~100)
    long_sentence_ratio: Mapped[int] = mapped_column(Integer)
    #: 문단당 문장 수
    paragraph_avg_sentences: Mapped[int] = mapped_column(Integer)
    #: 1,000자당 숫자 표현 개수. 성과를 숫자로 쓰는 습관을 본다
    numeric_density: Mapped[int] = mapped_column(Integer)

    # --- 표현 (화이트리스트 기능어만) ---
    #: 자주 쓰는 종결 어미 (예: 했습니다 · 입니다)
    endings: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list, server_default="{}")
    #: 자주 쓰는 연결어 (예: 그래서 · 또한)
    connectives: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), default=list, server_default="{}"
    )

    # --- 출처 ---
    #: 이 프로필을 만든 글의 글자 수. 1,000자 미만으로는 만들지 않는다 (tasks.md A14)
    source_chars: Mapped[int] = mapped_column(Integer)
    #: 센 문장 수. 적은 표본으로 만든 프로필인지 사용자가 판단할 근거다
    sentence_count: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
