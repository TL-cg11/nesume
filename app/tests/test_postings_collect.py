"""C4 서울시 응답 파서·fetch 테스트. DB·네트워크 불필요(순수 + transport 주입)."""
from datetime import date

import pytest

from app.postings.collect import (
    _extract_page,
    _extract_salary,
    _parse_date,
    fetch_all_seoul,
    parse_seoul_row,
)

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


# --- fetch 페이지네이션 (transport 주입, 네트워크 없음) ---

def _page(rows: list[dict], total: int) -> dict:
    return {"recMntList": {"RESULT": {"CODE": "INFO-000"}, "row": rows, "list_total_count": total}}


def test_fetch_paginates_until_total():
    pages = {
        (1, 1000): _page([{"i": n} for n in range(1000)], 2300),
        (1001, 2000): _page([{"i": n} for n in range(1000)], 2300),
        (2001, 3000): _page([{"i": n} for n in range(300)], 2300),
    }
    got = fetch_all_seoul(fetch_page=lambda s, e: pages[(s, e)])
    assert len(got) == 2300  # 세 페이지 합산, 전체 건수 도달 시 종료


def test_fetch_stops_on_empty_page():
    got = fetch_all_seoul(fetch_page=lambda s, e: _page([], 0))
    assert got == []


def test_fetch_respects_max_calls():
    # 종료 조건이 안 와도 max_calls로 무한루프 방지
    got = fetch_all_seoul(fetch_page=lambda s, e: _page([{"i": 1}], 10_000_000), max_calls=3)
    assert len(got) == 3


def test_extract_page_raises_on_error_code():
    with pytest.raises(RuntimeError):
        _extract_page({"recMntList": {"RESULT": {"CODE": "ERROR-300", "MESSAGE": "bad key"}}})


@pytest.mark.parametrize(
    ("base", "ok"),
    [
        ("http://openapi.seoul.go.kr:8088", True),   # 서울시는 http 만 응답
        ("https://example.com", True),
        ("http://example.com", False),
        ("http://openapi.seoul.go.kr.evil.com:8088", False),
        ("ftp://openapi.seoul.go.kr", False),
    ],
)
def test_default_fetch_page_scheme(monkeypatch, base, ok):
    import app.postings.collect as collect

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    monkeypatch.setenv("SEOUL_OPENAPI_BASE_URL", base)
    monkeypatch.setenv("SEOUL_OPENAPI_KEY", "k")
    monkeypatch.setattr(collect, "urlopen", lambda url, timeout: _Resp())
    if ok:
        assert collect._default_fetch_page(1, 1) == {}
    else:
        with pytest.raises(ValueError):
            collect._default_fetch_page(1, 1)
