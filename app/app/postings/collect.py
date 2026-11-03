"""C4 — 서울 열린데이터광장 공고 수집 (파서 + 오케스트레이션).

파서 `parse_seoul_row`는 순수(stdlib만) — 응답 1건 dict를 모델 필드 dict로 변환한다.
`fetch_all_seoul`은 stdlib(urllib)로 전량 조회(주소·키는 env, D가 Secrets로 주입).
`run_collection`은 건강성 게이트 → upsert → 사라짐 처리 → 이력 기록을 묶는다(DB·A1 mask 필요).
스케줄(하루 1회 CronJob)·Secrets 주입은 D5 인프라.

저장 제외(Plan.md 1-6): CONTACT_TELNO·EMP_CHARGER_DPT(연락처)·CORP_ADDR·STRTNM_CD 등.
`job_content`엔 연락처가 섞일 수 있어 upsert 전에 A1 mask를 거친다(spec 공개 등급 마스킹).
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from urllib.request import urlopen

if TYPE_CHECKING:  # 타입만 — 런타임 DB/의존 import는 함수 안에서 지연 로드
    from sqlalchemy.orm import Session

SOURCE_SEOUL = "seoul"

#: 서울시 recMntList는 1회 최대 1,000건(Plan.md 1-6). 전량(~4만)은 여러 번 나눠 받는다.
SEOUL_PAGE_SIZE = 1000

#: 서울 열린데이터광장은 8088 포트에서 http 만 응답한다(https 핸드셰이크 실패, 10-29 확인).
#: 이 호스트만 http 를 허용하고 나머지는 https 만.
SEOUL_HTTP_HOST = "openapi.seoul.go.kr"

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


def _edu_range(lo: str | None, hi: str | None) -> str | None:
    """학력 글 범위(예: "대졸(4년)~석사"). 같거나 한쪽만 있으면 그 값."""
    lo, hi = (lo or "").strip(), (hi or "").strip()
    if lo and hi and lo != hi:
        return f"{lo}~{hi}"
    return lo or hi or None


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
        "career_text": row.get("CAREER") or None,
        "edu_text": _edu_range(row.get("MIN_EDUBG"), row.get("MAX_EDUBG")),
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


# ---- fetch (서울시 recMntList) ----
# transport(fetch_page)를 주입 가능하게 해, 네트워크 없이 페이지네이션 로직을 단위 테스트한다.

def _extract_page(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """응답 1페이지에서 (행 목록, 전체 건수) 추출. 오류는 HTTP 200 + 본문 코드로 옴(Plan.md 1-5)."""
    svc = payload.get("recMntList") or {}
    result = svc.get("RESULT") or {}
    code = result.get("CODE", "")
    if code and not code.startswith("INFO-0"):  # INFO-000 = 성공
        raise RuntimeError(f"Seoul API error: {code} {result.get('MESSAGE', '')}")
    return (svc.get("row") or []), int(svc.get("list_total_count") or 0)


def _default_fetch_page(start: int, end: int, *, timeout: int = 30) -> dict[str, Any]:
    """env의 서울시 주소·키로 한 페이지 조회(https, 서울시 호스트만 http). 키·주소는 D가 Secrets로 주입."""
    base = os.environ.get("SEOUL_OPENAPI_BASE_URL")
    key = os.environ.get("SEOUL_OPENAPI_KEY")
    if not base or not key:
        raise RuntimeError("SEOUL_OPENAPI_BASE_URL/SEOUL_OPENAPI_KEY env 필요 (D 주입)")
    url = f"{base.rstrip('/')}/{key}/json/recMntList/{start}/{end}/"
    parts = urlsplit(url)
    if not (parts.scheme == "https" or (parts.scheme == "http" and parts.hostname == SEOUL_HTTP_HOST)):
        raise ValueError("https URL만 허용(서울시 호스트만 http 예외)")
    with urlopen(url, timeout=timeout) as resp:  # 신뢰된 고정 API(env 기반) — 사용자 입력 아님
        return json.loads(resp.read().decode("utf-8"))


def fetch_all_seoul(
    *,
    fetch_page: Callable[[int, int], dict[str, Any]] | None = None,
    page_size: int = SEOUL_PAGE_SIZE,
    max_calls: int = 100,
) -> list[dict[str, Any]]:
    """서울시 공고 전량 조회(1,000건씩 페이지네이션). `fetch_page` 주입 시 테스트용.

    `max_calls`로 무한 루프 방지(전량 ~40회). 전체 건수 도달 또는 빈 페이지면 종료.
    """
    fetch_page = fetch_page or _default_fetch_page
    rows: list[dict[str, Any]] = []
    start, calls = 1, 0
    while calls < max_calls:
        page_rows, total = _extract_page(fetch_page(start, start + page_size - 1))
        rows.extend(page_rows)
        calls += 1
        if not page_rows or len(rows) >= total:
            break
        start += page_size
    return rows


def run_collection(
    session: Session,
    rows: list[dict[str, Any]],
    *,
    recent: list[int] | None = None,
    source: str = SOURCE_SEOUL,
    parse: Callable[[dict[str, Any]], dict[str, Any]] = parse_seoul_row,
) -> dict[str, Any]:
    """전량 재수집분 1회 처리: 건강성 게이트 → 파싱·mask·upsert → 사라짐 처리 → 이력 기록.

    `parse`는 응답 1건 → 필드 dict(기본 서울시). 이미 필드 dict인 출처(공채속보)는 그대로 넘기는 함수를 준다.
    사라짐 판정용 키는 **upsert와 같은 규칙**(`source_key`가 있으면 그걸로)으로 계산한다 — 다르면
    고유번호로 식별되는 공고가 매번 "사라짐"으로 잡힌다.

    `recent`(기준선용 최근 정상 건수)를 안 주면 `collection_runs`에서 읽는다. 처리 끝에
    이번 수집을 기록해 다음 게이트의 기준선이 된다. 반환: 요약(gate·액션 집계·비활성 수).
    """
    # 지연 import — 파서를 쓰는 쪽(테스트)이 DB/A1 없이도 모듈을 import할 수 있게.
    from app.pii import mask
    from app.postings.health import evaluate_health
    from app.postings.identity import Action, link_key
    from app.postings.upsert import apply_absences, recent_counts, record_run, upsert_posting

    if recent is None:
        recent = recent_counts(session, source=source)
    gate = evaluate_health(len(rows), recent)

    counts = {a: 0 for a in Action}
    seen: list[str] = []
    seen_set: set[str] = set()
    duplicates = 0
    for raw in rows:
        fields = parse(raw)
        lk = link_key(
            source=source,
            company=fields.get("company_name"),
            title=fields.get("title"),
            region_code=fields.get("region_code"),
            job_code=fields.get("job_code"),
            work_address=fields.get("work_address"),
            native_id=fields.get("source_key"),
        )
        # 같은 응답 안의 중복(서울시 4만 건 중 실측 있음)은 첫 건만. 세션이 autoflush=False 라
        # 두 번째도 NEW 로 INSERT 되어 부분 유니크(source, link_key, 활성)에 걸린다(10-29 dev).
        if lk in seen_set:
            duplicates += 1
            continue
        seen_set.add(lk)
        seen.append(lk)
        if fields.get("job_content"):  # 공개 등급 PII 마스킹(연락처 혼입 대비)
            fields["job_content"] = mask(fields["job_content"])
        for rf in fields.get("recruit_fields") or ():  # 분야별 직무내용도 같은 기준
            if rf.get("job_content"):
                rf["job_content"] = mask(rf["job_content"])
        _row, action = upsert_posting(session, source=source, fields=fields)
        counts[action] += 1

    deactivated = apply_absences(session, source=source, seen_link_keys=seen, gate=gate)
    record_run(session, source=source, received=len(rows), healthy=gate.healthy, reason=gate.reason)
    return {
        "gate": gate.reason,
        "healthy": gate.healthy,
        "received": len(rows),
        "actions": {a.value: counts[a] for a in Action},
        "duplicates": duplicates,
        "deactivated": deactivated,
    }
