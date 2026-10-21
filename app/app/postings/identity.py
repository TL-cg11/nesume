"""C4 — 공고 식별 (link_key·content_hash 생성 + 재공고 판별, 순수 로직).

식별 3층(docs/C4.md):
- **내부 ID** `job_postings.id` (불변 UUID) — 모델/DB가 발급, 여기선 안 다룸.
- **링크 키** — 같은 공고 재식별용 자연키. **날짜 미포함**(마감 연장으로 키가
  흔들리지 않게 — 재공고는 아래 gap으로 가린다).
- **내용 해시** — 변경 감지용. 마감일처럼 자주 바뀌는 값은 뺀다.

재공고 판별(결정 1): 링크 키가 같아도 **마지막 노출 이후 gap > 윈도우(14일)**면
새 공고(새 내부 ID). gap 이내면 같은 공고 — 비활성이었으면 복귀(재활성),
내용 해시가 다르면 변경(재임베딩).

순수 stdlib(hashlib). DB·외부 의존 없음.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.postings.normalize import normalize_code, normalize_company, normalize_title

#: 재공고 판별 윈도우 (docs/C4.md 결정 1, 2026-10-21)
REPOST_WINDOW_DAYS = 14

#: 필드 구분자 — 해시 입력에서 필드 경계를 고정(연접 모호성 방지). 본문에 안 나오는 제어문자.
_SEP = "\x1f"


def _sha256(basis: str) -> str:
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


# 식별력이 약한 일반어 제목 — 단독으로는 자동 병합을 보류(needs_review). docs/C4.md 결정1 보강.
GENERIC_TITLES: frozenset[str] = frozenset({
    "직원모집", "직원채용", "사원모집", "사원채용", "모집", "채용", "구인", "채용공고",
})


def link_key(
    *,
    source: str,
    company: str | None = None,
    title: str | None = None,
    region_code: str | None = None,
    job_code: str | None = None,
    work_address: str | None = None,
    native_id: str | None = None,
) -> str:
    """같은 공고를 다시 알아보는 자연키(sha256 hex).

    native_id가 있으면(사람인 공고ID·공채속보 empSeqno) 출처 고유 ID를 그대로 키로 쓴다.
    서울시처럼 고유번호가 없으면 정규화한 기업명·제목·지역·직종코드·근무지를 해시한다.
    근무지(work_address)는 같은 기업·제목·지역·직종의 지점 구분을 돕는다(결정1 보강).
    **날짜는 넣지 않는다** — 마감 연장으로 키가 바뀌면 같은 공고가 중복 생성되므로.
    """
    if native_id and native_id.strip():
        basis = _SEP.join((source, native_id.strip()))
    else:
        basis = _SEP.join((
            source,
            normalize_company(company),
            normalize_title(title),
            normalize_code(region_code),
            normalize_code(job_code),
            normalize_title(work_address),
        ))
    return _sha256(basis)


def is_reliable_key(
    *,
    company: str | None = None,
    title: str | None = None,
    native_id: str | None = None,
) -> bool:
    """이 link_key를 믿고 자동 병합해도 되는지. 거짓이면 needs_review로 격리(결정1 보강).

    native_id가 있으면 신뢰. 없으면 기업명·제목이 둘 다 있어야 하고,
    제목이 일반어("직원 모집" 등)거나 너무 짧으면 식별력 부족으로 본다.
    """
    if native_id and native_id.strip():
        return True
    company_norm = normalize_company(company)
    title_norm = normalize_title(title)
    if not company_norm or not title_norm:
        return False
    squashed = title_norm.replace(" ", "")
    return not (squashed in GENERIC_TITLES or len(squashed) < 2)


def content_hash(
    *,
    company: str | None,
    title: str | None,
    registered_on: date | str | None,
    job_code: str | None,
    region_code: str | None,
    job_content: str | None,
) -> str:
    """변경 감지용 해시. sha256(기업명·제목·등록일·직종코드·지역코드·직무내용).

    마감일은 자주 바뀌어 제외(필드만 갱신). 본문(job_content)은 임베딩 재료라
    원문 기준으로 비교(공백만 정리)해 실제 내용 변경을 잡는다.
    """
    basis = _SEP.join((
        normalize_company(company),
        normalize_title(title),
        str(registered_on or ""),
        normalize_code(job_code),
        normalize_code(region_code),
        " ".join((job_content or "").split()),
    ))
    return _sha256(basis)


class Action(StrEnum):
    """수집 시 공고 1건에 대한 처리 구분(docs/C4.md 수집 로직)."""

    NEW = "new"                      # 신규 또는 재공고 → 새 내부 ID 발급·insert·임베딩
    UNCHANGED = "unchanged"          # 동일 공고, 내용 그대로 → last_seen_at만 갱신
    CONTENT_CHANGED = "content_changed"  # 동일 공고, 내용 변경 → 내부 ID 유지·필드/해시 갱신·재임베딩
    REACTIVATED = "reactivated"      # 일시 누락 후 복귀 → 비활성 행 재활성(내용 바뀌었으면 함께 재임베딩)


@dataclass(frozen=True)
class ExistingPosting:
    """같은 link_key로 조회된 기존 공고의 식별 판단에 필요한 최소 상태."""

    content_hash: str
    #: 연속 '정상 수집'에서 이 공고가 안 보인 횟수(달력일 아님). 수집 장애일엔 안 늘어난다.
    missing_streak: int
    is_active: bool


def classify(
    existing: ExistingPosting | None,
    *,
    incoming_content_hash: str,
    repost_window: int = REPOST_WINDOW_DAYS,
) -> Action:
    """기존 공고 상태와 오늘 수집분을 비교해 처리 구분을 결정한다.

    재공고 판별은 **달력 gap이 아니라 missing_streak(정상 수집 미노출 횟수)**로 한다.
    수집 장애로 며칠 안 돌아도 streak가 안 늘어, 장애 복귀분을 재공고로 오인하지 않는다
    (docs/C4.md 건강성 게이트).

    - 기존 없음 → NEW
    - missing_streak > window → 재공고 → NEW (옛 행은 비활성 유지, 새 내부 ID)
    - streak 이내 + 비활성 → REACTIVATED (일시 누락 후 복귀)
    - streak 이내 + 활성 + 해시 다름 → CONTENT_CHANGED
    - streak 이내 + 활성 + 해시 같음 → UNCHANGED
    """
    if existing is None:
        return Action.NEW
    if existing.missing_streak > repost_window:
        return Action.NEW
    if not existing.is_active:
        return Action.REACTIVATED
    if existing.content_hash != incoming_content_hash:
        return Action.CONTENT_CHANGED
    return Action.UNCHANGED
