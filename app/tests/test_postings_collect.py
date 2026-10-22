"""C4 서울시 응답 파서 테스트. DB·외부 불필요(순수 파서만)."""
from datetime import date

from app.postings.collect import _extract_salary, _parse_date, parse_seoul_row

SAMPLE = {
    "COMPANY": "㈜네수메",
    "TITLE": "백엔드 개발자",
    "JOBS_CD": "024000",
    "JOBS_NM": "응용SW개발자 (024000)",
    "REGION_CD": "11000",
    "REGION": "서울",
    "WORK_REGION": "서울 강남구",
    "ENTER_TP_CD": "N",
    "EMP_TP_CD": "01",
    "EMP_TP_NM": "정규직",
    "SAL_TP_CD": "M",
    "SAL_TP_NM": "월급2,600,000원 이상 ~ 3,000,000원",
    "COLLECT_PSNCNT": "0명",
    "JOB_CONT": "파이썬/FastAPI 경험 우대",
    "REG_DT": "26-10-01",
    "CLOSE_DT": "채용시까지  26-10-31",
    "RCPT_MTHD": "고용24",
    "CONTACT_TELNO": "010-1234-5678",   # 연락처 — 저장 제외 대상
    "EMP_CHARGER_DPT": "인사팀",         # 담당 부서 — 저장 제외 대상
}


def test_parse_maps_basic_fields():
    f = parse_seoul_row(SAMPLE)
    assert f["company_name"] == "㈜네수메"
    assert f["title"] == "백엔드 개발자"
    assert f["region_code"] == "11000"
    assert f["apply_method"] == "고용24"


def test_parse_strips_trailing_code_from_job_name():
    assert parse_seoul_row(SAMPLE)["job_name"] == "응용SW개발자"


def test_parse_dates_two_digit_year():
    f = parse_seoul_row(SAMPLE)
    assert f["registered_on"] == date(2026, 10, 1)
    assert f["closes_on"] == date(2026, 10, 31)  # "채용시까지" 접두어가 있어도 날짜 추출
    assert f["until_filled"] is True


def test_parse_salary_and_headcount():
    f = parse_seoul_row(SAMPLE)
    assert f["salary_min"] == 2600000
    assert f["salary_max"] == 3000000
    assert f["headcount"] == 0


def test_parse_excludes_contact_fields():
    f = parse_seoul_row(SAMPLE)
    assert "CONTACT_TELNO" not in f.values()
    assert "contact" not in " ".join(f.keys())
    assert "010-1234-5678" not in str(f)  # 연락처가 어떤 필드로도 새지 않음


def test_parse_seoul_has_no_native_source_key():
    assert parse_seoul_row(SAMPLE)["source_key"] is None  # 고유번호 없음 → link_key로 식별


def test_parse_date_edge_cases():
    assert _parse_date(None) is None
    assert _parse_date("상시채용") is None
    assert _parse_date("2026-01-05") == date(2026, 1, 5)  # 4자리 연도도 처리


def test_extract_salary_single_amount():
    lo, hi = _extract_salary("월급 2,500,000원")
    assert lo == 2500000
    assert hi is None  # 단일 금액이면 상한 없음


def test_extract_salary_none():
    assert _extract_salary(None) == (None, None)
    assert _extract_salary("회사내규에 따름") == (None, None)
