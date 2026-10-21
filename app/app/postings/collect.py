"""C4 — 서울 열린데이터광장 공고 수집 (파서 + 오케스트레이션).

파서 `parse_seoul_row`는 순수(stdlib만) — 응답 1건 dict를 모델 필드 dict로 변환한다.
`run_collection`은 건강성 게이트 → upsert → 사라짐 처리를 묶는다(DB·A1 mask 필요).
실제 호출(httpx)·스케줄(하루 1회 CronJob)은 D5 인프라. 여기선 로직만.

저장 제외(Plan.md 1-6): CONTACT_TELNO·EMP_CHARGER_DPT(연락처)·CORP_ADDR·STRTNM_CD 등.
`job_content`엔 연락처가 섞일 수 있어 upsert 전에 A1 mask를 거친다(spec 공개 등급 마스킹).
"""
from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 타입만 — 런타임 DB/의존 import는 함수 안에서 지연 로드
    from sqlalchemy.orm import Session

SOURCE_SEOUL = "seoul"

_DATE_RE = re.compile(r"(\d{2}|\d{4})-(\d{1,2})-(\d{1,2})")
_NUM_RE = re.compile(r"\d[\d,]*")
_TRAILING_CODE_RE = re.compile(r"\s*\(\s*\d+\s*\)\s*$")  # JOBS_NM 끝의 "(코드)" 제거


def _parse_date(s: str | None) -> date | None:
    """'YY-MM-DD'/'YYYY-MM-DD'(접두어 '채용시까지' 등 섞여도)에서 날짜 추출. 2자리 연도 → 20YY."""
    if not s:
        return None
    m = _DATE_RE.search(s)
    if not m:
        return None
    year, month, day = m.groups()
    y = int(year)
    if len(year) == 2:
        y += 2000
    try:
        return date(y, int(month), int(day))
    except ValueError:
        return None


def _to_int(s: str | None) -> int | None:
    """문자열에서 첫 숫자(천단위 콤마 허용)를 정수로. 없으면 None."""
    if not s:
        return None
    m = _NUM_RE.search(s)
    return int(m.group().replace(",", "")) if m else None


def _extract_salary(text: str | None) -> tuple[int | None, int | None]:
    """'월급2,600,000원 이상 ~ 3,000,000원' 류에서 최소·최대 금액 추출(best-effort)."""
    if not text:
        return None, None
    nums = [int(n.replace(",", "")) for n in _NUM_RE.findall(text)]
    # 1,000 미만은 금액이 아닐 가능성(연차 등) → 제외
    amounts = [n for n in nums if n >= 1000]
    if not amounts:
        return None, None
    return min(amounts), (max(amounts) if len(amounts) > 1 else None)


def parse_seoul_row(row: dict[str, Any]) -> dict[str, Any]:
    """서울시 recMntList 응답 1건 → `JobPosting` 필드 dict(순수). 연락처 필드는 담지 않는다."""
    close_text = row.get("CLOSE_DT")
    job_name = row.get("JOBS_NM") or ""
    salary_text = row.get("SAL_TP_NM")
    salary_min, salary_max = _extract_salary(salary_text)
    return {
        "source_key": None,  # 서울시는 고유번호 없음 → link_key(계산값)로 식별
        "company_name": row.get("COMPANY"),
        "title": row.get("TITLE"),
        "job_code": row.get("JOBS_CD"),
        "job_name": _TRAILING_CODE_RE.sub("", job_name) or None,
        "industry_name": row.get("IND_TP_CD_NM"),
        "region_code": row.get("REGION_CD"),
        "region_name": row.get("REGION"),
        "work_address": row.get("WORK_REGION"),
        "career_code": row.get("ENTER_TP_CD"),
        "min_edu_code": row.get("MIN_EDUBG_ICD"),
        "max_edu_code": row.get("MAX_EDUBG_ICD"),
        "emp_type_code": row.get("EMP_TP_CD"),
        "emp_type_text": row.get("EMP_TP_NM"),
        "salary_type_code": row.get("SAL_TP_CD"),
        "salary_text": salary_text,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "headcount": _to_int(row.get("COLLECT_PSNCNT")),
        "job_content": row.get("JOB_CONT"),
        "certificates": row.get("CERTIFICATE"),
        "preferred": row.get("PF_COND"),
        "major": row.get("MAJOR"),
        "computer_skills": row.get("COMP_ABL"),
        "selection_method": row.get("SEL_MTHD"),
        "apply_method": row.get("RCPT_MTHD"),
        "required_docs": row.get("SUBMIT_DOC"),
        "work_hours_text": row.get("WORKDAY_WORKHR_CONT"),
        "insurance_text": row.get("FOUR_INS"),
        "retirement_text": row.get("RETIREPAY"),
        "welfare_text": row.get("ETC_WELFARE"),
        "registered_on": _parse_date(row.get("REG_DT")),
        "close_text": close_text,
        "closes_on": _parse_date(close_text),
        "until_filled": bool(close_text and "채용시까지" in close_text),
        "source_url": None,  # 서울시는 원문 링크 없음
    }


def run_collection(
    session: Session,
    rows: list[dict[str, Any]],
    *,
    recent_counts: list[int],
    source: str = SOURCE_SEOUL,
) -> dict[str, Any]:
    """전량 재수집분 1회 처리: 건강성 게이트 → 파싱·mask·upsert → 사라짐 처리.

    `recent_counts`: 최근 정상 수집 건수 이력(게이트 기준선). 호출측(수집 이력 저장, D)에서 공급.
    반환: 처리 요약(gate reason·upsert 액션 집계·비활성 건수).
    """
    # 지연 import — 파서를 쓰는 쪽(테스트)이 DB/A1 없이도 모듈을 import할 수 있게.
    from app.pii import mask
    from app.postings.health import evaluate_health
    from app.postings.identity import Action, link_key
    from app.postings.upsert import apply_absences, upsert_posting

    gate = evaluate_health(len(rows), recent_counts)

    counts = {a: 0 for a in Action}
    seen: list[str] = []
    for raw in rows:
        fields = parse_seoul_row(raw)
        if fields.get("job_content"):  # 공개 등급 PII 마스킹(연락처 혼입 대비)
            fields["job_content"] = mask(fields["job_content"])
        seen.append(
            link_key(
                source=source,
                company=fields.get("company_name"),
                title=fields.get("title"),
                region_code=fields.get("region_code"),
                job_code=fields.get("job_code"),
                work_address=fields.get("work_address"),
            )
        )
        _row, action = upsert_posting(session, source=source, fields=fields)
        counts[action] += 1

    deactivated = apply_absences(session, source=source, seen_link_keys=seen, gate=gate)
    return {
        "gate": gate.reason,
        "healthy": gate.healthy,
        "received": len(rows),
        "actions": {a.value: counts[a] for a in Action},
        "deactivated": deactivated,
    }
