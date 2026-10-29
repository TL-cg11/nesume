"""C4 — 공고 필드 조회 창구 (A11 매칭·분석이 쓰는 읽기 경로).

A11(`features/matching`)은 공고 글이 필요하지만 **C4 모델을 직접 읽지 않는다** — 남의 테이블을
각자 읽으면 접근 통제·조회 로직이 두 곳으로 갈라진다(A8·C6 어댑터와 같은 문제, A 메시지 2026-10-22).
그래서 공고를 읽는 창구는 **C가 하나만 연다**. A는 이 함수만 호출하고 `JobPosting` ORM은 모른다
→ C4가 컬럼을 바꿔도 A 코드는 안 깨지고, 변경은 이 함수 한 곳만 고치면 된다.

대부분(`source` seoul/saramin/work24_open)은 `grade=public`이라 누구나 조회 가능하지만,
**`source='user'`(사용자 직접 입력) 공고는 `owner_user_id` 본인만 조회**가 규약이다
(`models/posting.py` SOURCES). 창구를 하나로 모은 이상 **권한 검사도 여기서** 한다 — 그래서
호출자의 `user_id`를 받아 **남의 비공개 공고는 `None`**으로 막는다(A 지적, 2026-10-22). UUID를
알아야 조회되니 열거는 원래 안 되지만, 소유자 확인이 없으면 UUID를 아는 제3자가 읽을 수 있었다.

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


def get_posting_fields(
    session: Session, posting_id: uuid.UUID, *, user_id: str
) -> dict[str, str | None] | None:
    """공고 1건의 분석용 필드를 돌려준다. 없거나 **볼 권한이 없으면** None.

    `user_id`는 호출자(A11 라우터의 `user.sub`)다 — 키워드 전용·필수로 둬서 **신원 없이 호출 불가**
    (fail-closed). `owner_user_id`가 있는 비공개 공고(`source='user'`)는 **소유자 본인일 때만** 반환,
    남의 것이면 "없음"과 구분 없이 `None`(존재 노출 안 함). 공개 출처는 `owner_user_id`가 없어 통과.

    반환은 평범한 dict(`POSTING_FIELDS` 키) — A11을 import하지 않아 양쪽이 서로 독립이다.
    A는 받은 dict으로 `PostingIn(**fields)`를 만든다(필드명을 C4 모델과 같게 맞춰 둠).
    비활성(`is_active=False`)·검토대상(`needs_review`) 공고도 그대로 돌려준다 — 공고가 내려가도
    사용자가 보던 공고를 분석할 수 있어야 하고, 노출 여부 판단은 조회 시점이 아니라 검색(C6)이 한다.
    """
    posting = session.get(JobPosting, posting_id)
    if posting is None:
        return None
    # 비공개(사용자 입력) 공고는 소유자만. 공개 출처는 owner_user_id가 None이라 통과.
    if posting.owner_user_id is not None and posting.owner_user_id != user_id:
        return None
    return {name: getattr(posting, name) for name in POSTING_FIELDS}


def get_posting_link(
    session: Session, posting_id: uuid.UUID, *, user_id: str
) -> dict[str, str | None] | None:
    """추천 화면용 출처·원문 링크·회사명(`source`, `source_url`, `company_name`).

    권한 규칙은 `get_posting_fields`와 같다.

    `POSTING_FIELDS`에 넣지 않고 따로 둔다 — A11은 그 dict로 `PostingIn(**fields)`(extra="forbid")를
    만들어서, 키를 늘리면 A 쪽이 깨진다. 링크는 서울시 공고엔 없어 None(공채속보만 있음).
    """
    posting = session.get(JobPosting, posting_id)
    if posting is None:
        return None
    if posting.owner_user_id is not None and posting.owner_user_id != user_id:
        return None
    return {"source": posting.source, "source_url": posting.source_url, "company_name": posting.company_name}


#: 공고 상세 화면에 보여줄 원문 필드(라벨, 컬럼) — 화면 순서.
#: 매칭용 키워드(A11)가 아니라 **공고에 적힌 글 그대로**.
DETAIL_FIELDS = (
    ("고용형태", "emp_type_text"),
    ("경력", "career_text"),
    ("학력", "edu_text"),
    ("근무지역", "region_name"),
    ("근무지", "work_address"),
    ("급여", "salary_text"),
    ("근무시간", "work_hours_text"),
    ("마감", "close_text"),
    ("자격", "certificates"),
    ("우대", "preferred"),
    ("전공", "major"),
    ("컴퓨터 활용", "computer_skills"),
    ("전형", "selection_method"),
    ("접수방법", "apply_method"),
    ("제출서류", "required_docs"),
)


def get_posting_detail(session: Session, posting_id: uuid.UUID, *, user_id: str) -> dict | None:
    """공고 상세(원문). 권한 규칙은 `get_posting_fields`와 같다 — 없거나 볼 권한이 없으면 None.

    `fields`는 값이 있는 항목만 `[{"label", "value"}]`(화면 순서), `job_content`는 직무내용 원문.
    A1 mask는 수집 때 `job_content`에 이미 적용됐다(collect.run_collection). 화면은 텍스트로만 렌더링한다.
    """
    posting = session.get(JobPosting, posting_id)
    if posting is None:
        return None
    if posting.owner_user_id is not None and posting.owner_user_id != user_id:
        return None
    rows = []
    for label, col in DETAIL_FIELDS:
        value = getattr(posting, col)
        if value is not None and str(value).strip():
            rows.append({"label": label, "value": str(value).strip()})
    return {
        "id": posting.id,
        "source": posting.source,
        "company_name": posting.company_name,
        "title": posting.title,
        "job_name": posting.job_name,
        "job_content": posting.job_content,
        "fields": rows,
        "url": posting.source_url,
        "is_active": posting.is_active,
    }
