"""C4 — 공고 필드 조회 창구 (A11 매칭·분석이 쓰는 읽기 경로).

A11(`features/matching`)은 공고 글이 필요하지만 **C4 모델을 직접 읽지 않는다** — 남의 테이블을
각자 읽으면 접근 통제·조회 로직이 두 곳으로 갈라진다(A8·C6 어댑터와 같은 문제, A 메시지 2026-10-22).
그래서 공고를 읽는 창구는 **C가 하나만 연다**. A는 이 함수만 호출하고 `JobPosting` ORM은 모른다
→ C4가 컬럼을 바꿔도 A 코드는 안 깨지고, 변경은 이 함수 한 곳만 고치면 된다.

공고는 `grade=public`이라 **역할 필터 없이 단순 조회**면 충분하다(개인 문서인 자소서·경험과 다름).
PII 마스킹·C5 전처리는 **호출자(A11 `prepare_posting`)가 직접** 하므로 여기선 **원문 그대로** 돌려준다
(이중 마스킹 금지).
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.posting import JobPosting

#: A11이 공고에서 보는 필드(= `features/matching` PostingIn/PostingFields와 동일 키).
POSTING_FIELDS = (
    "title",
    "job_name",
    "job_content",
    "certificates",
    "preferred",
    "major",
    "computer_skills",
)


def get_posting_fields(session: Session, posting_id: uuid.UUID) -> dict[str, str | None] | None:
    """공고 1건의 분석용 필드를 돌려준다. 없으면 None.

    반환은 평범한 dict(`POSTING_FIELDS` 키) — A11을 import하지 않아 양쪽이 서로 독립이다.
    A는 받은 dict으로 `PostingIn(**fields)`를 만든다(필드명을 C4 모델과 같게 맞춰 둠).
    비활성(`is_active=False`)·검토대상(`needs_review`) 공고도 그대로 돌려준다 — 공고가 내려가도
    사용자가 보던 공고를 분석할 수 있어야 하고, 노출 여부 판단은 조회 시점이 아니라 검색(C6)이 한다.
    """
    posting = session.get(JobPosting, posting_id)
    if posting is None:
        return None
    return {name: getattr(posting, name) for name in POSTING_FIELDS}
