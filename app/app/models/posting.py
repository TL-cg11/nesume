"""공고 테이블 (C4 소유 모델). 수집 파이프라인이 적재하고 추천·검색이 조회한다.

식별 설계(docs/C4.md) — Plan.md 4-1 v5 초안에서 **진화**한 형태:
- **내부 ID `id`(불변 UUID)** — 모든 참조(지원 기록 C15·자소서)가 이것만 본다.
  v5 초안의 bigint이 아니라 UUID: 이미 머지된 `applications.job_posting_id`(Uuid)에 맞춤(강제).
- **`link_key`(재식별용)** — 정규화한 기업명·제목·지역·직종코드(+근무지)를 해시. **날짜 미포함**.
  v5의 "source_key = content_hash(내용=식별)"와 다름: 내용이 바뀌어도 내부 ID를 유지해야
  지원 기록 참조가 안 끊긴다(C15). 내용 변경은 `content_hash`로 따로 감지.
- **재공고 판별** — 같은 link_key라도 **정상 수집 N회 연속 미노출(missing_streak>14)**이면 새 공고.
  달력일이 아니라 '정상 수집 횟수' 기준 → 수집 장애에 시계가 멈춤(docs/C4.md 건강성 게이트).

FK 정책(docs/C4.md 결정 2 보강, 테이블별로 다름):
- `applications`·`resumes` → `job_postings` : **RESTRICT** (참조 중 공고 물리 삭제 금지).
  ※ 참조 컬럼은 B 소유 모델이므로 FK 자체는 **B 마이그레이션에서 추가**(C는 정책만 명시).
- `job_posting_embeddings` → `job_postings` : **CASCADE** (파생 데이터, 공고 삭제 시 함께 삭제).

※ 마이그레이션 번호·`models/__init__.py` 등록은 B가 취합(tasks.md).
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import (
    CreatedAt,
    Grade,
    UpdatedAt,
    UuidPk,
    grade_check,
    grade_column,
    one_of,
)

#: 공고 출처 (Plan.md 4-1). user = 사용자 직접 입력(해당 사용자만 조회).
SOURCES = ("seoul", "saramin", "work24_open", "user")


class JobPosting(Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        one_of("source", SOURCES, "job_postings_source"),
        grade_check(),
        # 활성 공고는 (source, link_key)당 하나. 과거 재공고 행은 is_active=false로 공존.
        Index(
            "uq_job_postings_source_linkkey_active",
            "source",
            "link_key",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("ix_job_postings_active_closes", "is_active", "closes_on"),
        Index("ix_job_postings_job_code", "job_code"),
        Index("ix_job_postings_region_code", "region_code"),
    )

    # --- 식별·수명주기 (C4 핵심) ---
    id: Mapped[UuidPk]
    source: Mapped[str] = mapped_column(String(16))
    #: 재식별 자연키 = sha256 hex(정규화 필드). native_id 있는 출처는 hash(source+native_id).
    link_key: Mapped[str] = mapped_column(String(64), index=True)
    #: 변경 감지용 해시. link_key 같고 이 값 다르면 '같은 공고의 내용 변경' → 재임베딩.
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    #: 출처 고유 ID 원본(사람인 공고ID·공채속보 empSeqno). 서울시는 없어 null. 디버깅·역추적용.
    source_key: Mapped[str | None] = mapped_column(Text)
    #: 사용자 입력 공고만 값. 공개 공고는 null. 사용자 삭제 시 함께 삭제.
    owner_user_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    grade: Mapped[str] = grade_column(Grade.PUBLIC)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    #: 식별 신뢰도 낮음(기업명·제목 결측, 일반어 제목) → 자동 병합 보류·검토 대상(docs/C4.md 결정1 보강).
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    #: 연속 정상 수집에서 '이 공고가 안 보인' 횟수. 재공고(>14)·삭제후보(>30)·백스톱(>90) 판정 기준.
    #: 달력일이 아니라 '정상 수집 횟수'라 수집 장애일엔 안 늘어난다(건강성 게이트).
    missing_streak: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    #: 수집 작업이 이 공고를 마지막으로/처음 본 시각(KST, tz-aware).
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- 기본 정보 (Plan.md 4-1, 서울시 응답 기준) ---
    company_name: Mapped[str | None] = mapped_column(Text)        # COMPANY
    title: Mapped[str | None] = mapped_column(Text)               # TITLE
    job_code: Mapped[str | None] = mapped_column(String(6))       # JOBS_CD
    job_name: Mapped[str | None] = mapped_column(Text)            # JOBS_NM (끝 (코드) 제거)
    industry_name: Mapped[str | None] = mapped_column(Text)       # IND_TP_CD_NM
    region_code: Mapped[str | None] = mapped_column(String(5))    # REGION_CD
    region_name: Mapped[str | None] = mapped_column(Text)         # REGION
    work_address: Mapped[str | None] = mapped_column(Text)        # WORK_REGION (link_key 보강에도 사용)

    # --- 조건·코드 ---
    career_code: Mapped[str | None] = mapped_column(String(1))    # ENTER_TP_CD (Z/E/N)
    career_text: Mapped[str | None] = mapped_column(Text)         # 화면 표시용 경력 글(서울 CAREER / 공채속보 empWantedCareerNm)
    edu_text: Mapped[str | None] = mapped_column(Text)            # 화면 표시용 학력 글(서울 MIN~MAX_EDUBG / 공채속보 empWantedEduNm)
    min_edu_code: Mapped[str | None] = mapped_column(String(2))   # MIN_EDUBG_ICD
    max_edu_code: Mapped[str | None] = mapped_column(String(2))   # MAX_EDUBG_ICD
    emp_type_code: Mapped[str | None] = mapped_column(String(2))  # EMP_TP_CD
    emp_type_text: Mapped[str | None] = mapped_column(Text)       # EMP_TP_NM (계약기간 포함)
    salary_type_code: Mapped[str | None] = mapped_column(String(1))  # SAL_TP_CD (M/H/Y/D)
    salary_text: Mapped[str | None] = mapped_column(Text)         # SAL_TP_NM 원본
    salary_min: Mapped[int | None] = mapped_column(Integer)       # 추출 실패 시 null
    salary_max: Mapped[int | None] = mapped_column(Integer)
    headcount: Mapped[int | None] = mapped_column(Integer)        # COLLECT_PSNCNT

    # --- 본문·요건 (갭 분석·임베딩 재료) ---
    job_content: Mapped[str | None] = mapped_column(Text)         # JOB_CONT (연락처 섞임 가능 → mask)
    certificates: Mapped[str | None] = mapped_column(Text)        # CERTIFICATE
    preferred: Mapped[str | None] = mapped_column(Text)           # PF_COND
    major: Mapped[str | None] = mapped_column(Text)               # MAJOR
    computer_skills: Mapped[str | None] = mapped_column(Text)     # COMP_ABL

    # --- 절차·복리 ---
    selection_method: Mapped[str | None] = mapped_column(Text)    # SEL_MTHD
    apply_method: Mapped[str | None] = mapped_column(Text)        # RCPT_MTHD (원문 링크 없어 화면 표시용)
    required_docs: Mapped[str | None] = mapped_column(Text)       # SUBMIT_DOC
    work_hours_text: Mapped[str | None] = mapped_column(Text)     # WORKDAY_WORKHR_CONT
    insurance_text: Mapped[str | None] = mapped_column(Text)      # FOUR_INS
    retirement_text: Mapped[str | None] = mapped_column(Text)     # RETIREPAY
    welfare_text: Mapped[str | None] = mapped_column(Text)        # ETC_WELFARE

    # --- 날짜·링크 ---
    registered_on: Mapped[date | None] = mapped_column(Date)      # REG_DT (4자리 연도로 변환)
    close_text: Mapped[str | None] = mapped_column(Text)          # CLOSE_DT 원본
    closes_on: Mapped[date | None] = mapped_column(Date)          # CLOSE_DT에서 추출
    until_filled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )  # "채용시까지" 포함 여부
    source_url: Mapped[str | None] = mapped_column(Text)          # 서울시는 없음(사람인·공채속보용)

    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class CollectionRun(Base):
    """수집 1회 기록. 건강성 게이트의 기준선(최근 정상 수집 건수의 중앙값)을 소스별로 낸다."""

    __tablename__ = "collection_runs"
    __table_args__ = (Index("ix_collection_runs_source_ran", "source", "ran_at"),)

    id: Mapped[UuidPk]
    source: Mapped[str] = mapped_column(String(16), index=True)
    received: Mapped[int] = mapped_column(Integer)   # 이번에 받은 공고 건수
    healthy: Mapped[bool] = mapped_column(Boolean)   # 게이트 정상 판정 여부
    reason: Mapped[str] = mapped_column(String(64))  # 게이트 사유 (ok/below-rel/bootstrap 등)
    ran_at: Mapped[CreatedAt]
