"""멘토 공유 문단별 코멘트 (tasks B17, spec 3.7, part2_guide 4.47).

코멘트는 작성자 자소서에 딸린 데이터다: owner_id = 자소서 작성자, 등급 개인, 대응표도 작성자 소유.
코멘트를 쓴 멘토는 shares.shared_with로 알 수 있다.
- 위치: 공유 시점에 고정된 버전(version_id ∈ shares.version_ids)의 문단 번호(빈 줄 기준, 0부터)
- 본문: 민감정보 거부 + 토큰화 저장(B4·B7과 같은 처리). 작성자에게는 원문, 멘토에게는 비공개 문구
- 공유가 끝나도 작성자는 계속 볼 수 있다. 공유·자소서·계정 삭제 시 함께 삭제(CASCADE)
"""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, Grade, UpdatedAt, UuidPk, grade_check, grade_column, owner_fk


class ShareComment(Base):
    __tablename__ = "share_comments"
    __table_args__ = (
        grade_check(),
        CheckConstraint("paragraph_index >= 0", name="paragraph_index_nonneg"),
    )

    id: Mapped[UuidPk]
    share_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shares.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = owner_fk()
    # FK 없음(shares.version_ids와 같은 방식). 공유에 고정된 버전인지는 서비스에서 확인한다
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    paragraph_index: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)  # PII 토큰화 상태
    vault_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("pii_vaults.id"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 작성자 확인 표시
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
