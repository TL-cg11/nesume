"""C4 고용24 공채속보 수집 테스트. 파서는 실제 응답 모양(2026-10-28, XML) 기준·순수,
`run_collection`·조회 창구는 DB 필요(conftest `db_session`).
"""
import datetime
import urllib.error
import uuid

import pytest
from sqlalchemy import select

from app.models.posting import JobPosting
from app.postings import work24_open
from app.postings.collect import run_collection
from app.postings.read import get_posting_fields, get_posting_link
from app.postings.work24_open import (
    DETAIL_PATH,
    LIST_PATH,
    SOURCE_WORK24_OPEN,
    Work24OpenError,
    fetch_all,
    parse_detail,
    parse_list,
    parse_xml,
    safe_link,
)

_LIST = b"""<?xml version="1.0" encoding="UTF-8"?>
<dhsOpenEmpInfoList><total>2</total><startPage>1</startPage><display>100</display>
<dhsOpenEmpInfo><empSeqno>183003</empSeqno><empWantedTitle>t1</empWantedTitle></dhsOpenEmpInfo>
<dhsOpenEmpInfo><empSeqno>183004</empSeqno><empWantedTitle>t2</empWantedTitle></dhsOpenEmpInfo>
</dhsOpenEmpInfoList>"""

# 실제 상세 모양(한국언론진흥재단 공고) — inqryCont·regLogImgNm·자소서 문항은 실제 응답처럼 둔다.
_DETAIL = """<?xml version="1.0" encoding="UTF-8"?>
<dhsOpenEmpInfoDetailRoot>
<empSeqno>{seq}</empSeqno>
<empWantedTitle>2026년 3차 체험형 청년인턴 모집 공고[일반행정, AI]</empWantedTitle>
<empBusiNm>한국언론진흥재단</empBusiNm><coClcdNm>공공기관</coClcdNm>
<empWantedStdt>20261026</empWantedStdt><empWantedEndt>20261109</empWantedEndt>
<empWantedHomepg>http://www.kpf.or.kr</empWantedHomepg>
<empWantedHomepgDetail>{link}</empWantedHomepgDetail>
<regLogImgNm>http://www.work.go.kr/framework/filedownload/logo.png</regLogImgNm>
<empWantedTypeNm>기간제|기타</empWantedTypeNm>
<empSelfintroList><empSelsListInfo>
 <selfintroQstCont>자소서 문항</selfintroQstCont>
</empSelsListInfo></empSelfintroList>
<empRecrList>
 <empRecrListInfo><empRecrNm>일반행정(본사)</empRecrNm><jobCont>상세 모집요강 참조</jobCont>
  <sptCertEtc></sptCertEtc><workRegionNm>서울 중구</workRegionNm></empRecrListInfo>
 <empRecrListInfo><empRecrNm>AI</empRecrNm><jobCont>AI 서비스 기획</jobCont></empRecrListInfo>
</empRecrList>
<empJobsList><empJobsListInfo><jobsCd>024</jobsCd><jobsCdKorNm>소프트웨어</jobsCdKorNm></empJobsListInfo></empJobsList>
<recrCommCont>[지원 자격] 학력 무관</recrCommCont>
<empSubmitDocCont>입사지원서</empSubmitDocCont>
<empRcptMthdCont>온라인 접수</empRcptMthdCont>
<inqryCont>문의: 02-2001-7777 recruit@kpf.or.kr</inqryCont>
</dhsOpenEmpInfoDetailRoot>"""


def _detail(seq="183003", link="https://kpf.plusrecruit.co.kr/#/recruitment/detail/46"):
    return _DETAIL.format(seq=seq, link=link).encode()


# --------------------------------------------------------------------------
# 파서 (순수)
# --------------------------------------------------------------------------

def test_parse_detail_maps_real_fields():
    f = parse_detail(parse_xml(_detail()))
    assert f["source_key"] == "183003"
    assert f["company_name"] == "한국언론진흥재단"
    assert f["title"].startswith("2026년 3차")
    assert f["source_url"] == "https://kpf.plusrecruit.co.kr/#/recruitment/detail/46"
    assert f["registered_on"] == datetime.date(2026, 10, 26)
    assert f["closes_on"] == datetime.date(2026, 11, 9)
    assert f["region_name"] == "서울 중구"
    assert (f["job_code"], f["job_name"]) == ("024", "소프트웨어")
    assert f["apply_method"] == "온라인 접수"
    assert "일반행정(본사): 상세 모집요강 참조" in f["job_content"]
    assert "AI: AI 서비스 기획" in f["job_content"]
    assert "[지원 자격]" in f["job_content"]


def test_parse_detail_drops_contact_logo_and_selfintro():
    """문의처(연락처)·로고·자소서 문항은 어디에도 실리지 않는다(화이트리스트)."""
    dumped = repr(parse_detail(parse_xml(_detail())))
    for leaked in ("02-2001-7777", "recruit@kpf.or.kr", "logo.png", "자소서 문항"):
        assert leaked not in dumped


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://kpf.plusrecruit.co.kr/#/x", True),
        ("http://www.kpf.or.kr", True),  # 기업 외부 도메인 — 스킴만 검사
        ("javascript:alert(1)", False),
        ("data:text/html,x", False),
        ("ftp://x.com/a", False),
        ("", False),
    ],
)
def test_safe_link_scheme_only(url, ok):
    assert (safe_link(url) is not None) is ok


def test_bad_detail_link_is_dropped_not_the_posting():
    f = parse_detail(parse_xml(_detail(link="javascript:alert(1)")))
    assert f["source_url"] == "http://www.kpf.or.kr"  # 상세 링크가 불량이면 홈페이지로 폴백
    assert f["title"]


def test_parse_list():
    seqnos, total = parse_list(parse_xml(_LIST))
    assert seqnos == ["183003", "183004"] and total == 2


@pytest.mark.parametrize(
    "body",
    [
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>',
        b'<?xml version="1.0"?><!ENTITY a SYSTEM "file:///etc/passwd"><x/>',
        b"<error>\xec\x9d\xb8\xec\xa6\x9d\xed\x82\xa4 \xec\x98\xa4\xeb\xa5\x98</error>",
        b"<root><error>bad key</error></root>",
        b"not xml",
    ],
)
def test_parse_xml_rejects_dtd_error_and_garbage(body):
    with pytest.raises(Work24OpenError):
        parse_xml(body)


# --------------------------------------------------------------------------
# fetch_all (목록 → 상세)
# --------------------------------------------------------------------------

def test_fetch_all_lists_then_details():
    calls = []

    def fetch(path, params):
        calls.append((path, params.get("startPage") or params.get("empSeqno")))
        return _LIST if path == LIST_PATH else _detail(seq=params["empSeqno"])

    rows = fetch_all(fetch)
    assert [r["source_key"] for r in rows] == ["183003", "183004"]
    assert calls == [(LIST_PATH, 1), (DETAIL_PATH, "183003"), (DETAIL_PATH, "183004")]


def test_fetch_all_caps_list_pages():
    pages = []

    def fetch(path, params):
        if path == LIST_PATH:
            pages.append(params["startPage"])
            n = params["startPage"]
            item = f"<dhsOpenEmpInfo><empSeqno>{n}</empSeqno></dhsOpenEmpInfo>"
            return f"<r><total>9999</total>{item}</r>".encode()
        return _detail(seq=params["empSeqno"])

    fetch_all(fetch, max_pages=3)
    assert pages == [1, 2, 3]


def test_http_fetch_hides_key(monkeypatch):
    secret = "SECRET-JOB-KEY"
    monkeypatch.setenv("WORK24_JOB_API_KEY", secret)
    monkeypatch.setenv("WORK24_API_BASE_URL", "https://www.work24.go.kr")

    def boom(url, timeout):
        raise urllib.error.HTTPError(url, 500, "err", {}, None)

    monkeypatch.setattr(work24_open.urllib.request, "urlopen", boom)
    with pytest.raises(Work24OpenError) as ei:
        work24_open.http_fetch(LIST_PATH, {"callTp": "L"})
    assert secret not in str(ei.value)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__


def test_http_fetch_requires_https_and_key(monkeypatch):
    monkeypatch.setenv("WORK24_JOB_API_KEY", "k")
    monkeypatch.setenv("WORK24_API_BASE_URL", "http://www.work24.go.kr")
    with pytest.raises(Work24OpenError):
        work24_open.http_fetch(LIST_PATH, {})
    monkeypatch.setenv("WORK24_API_BASE_URL", "https://www.work24.go.kr")
    monkeypatch.delenv("WORK24_JOB_API_KEY")
    with pytest.raises(Work24OpenError):
        work24_open.http_fetch(LIST_PATH, {})


# --------------------------------------------------------------------------
# run_collection·조회 창구 (DB)
# --------------------------------------------------------------------------

def _rows(n=2):
    return [parse_detail(parse_xml(_detail(seq=str(183000 + i)))) for i in range(n)]


def _postings(session):
    return session.execute(
        select(JobPosting).where(JobPosting.source == SOURCE_WORK24_OPEN)
    ).scalars().all()


def test_run_collection_stores_link_and_masks(db_session):
    rows = _rows(1)
    rows[0]["job_content"] += "\n문의 010-1234-5678"
    summary = run_collection(db_session, rows, source=SOURCE_WORK24_OPEN, parse=dict, recent=[])
    db_session.flush()

    (p,) = _postings(db_session)
    assert summary["received"] == 1
    assert p.source_key == "183000"
    assert p.source_url == "https://kpf.plusrecruit.co.kr/#/recruitment/detail/46"
    assert "010-1234-5678" not in (p.job_content or "")  # A1 mask


def test_run_collection_keeps_posting_seen_by_native_id(db_session):
    """정상 게이트에서 다시 받은 공고는 '사라짐'으로 비활성화되지 않는다(seen 키 = native_id 규칙)."""
    healthy = [2] * 7  # 부트스트랩 끝난 기준선 → 사라짐 처리 활성
    run_collection(db_session, _rows(2), source=SOURCE_WORK24_OPEN, parse=dict, recent=healthy)
    db_session.flush()
    summary = run_collection(db_session, _rows(2), source=SOURCE_WORK24_OPEN, parse=dict, recent=healthy)
    db_session.flush()

    assert summary["deactivated"] == 0
    assert all(p.is_active for p in _postings(db_session))


def test_get_posting_link_and_fields_unchanged(db_session):
    run_collection(db_session, _rows(1), source=SOURCE_WORK24_OPEN, parse=dict, recent=[])
    db_session.flush()
    (p,) = _postings(db_session)

    assert get_posting_link(db_session, p.id, user_id="anyone") == {
        "source": SOURCE_WORK24_OPEN,
        "source_url": "https://kpf.plusrecruit.co.kr/#/recruitment/detail/46",
        "company_name": p.company_name,
    }
    assert p.company_name  # 픽스처에 회사명이 있어야 위 비교가 의미 있다
    # A11용 창구는 키가 그대로(PostingIn extra="forbid")
    assert set(get_posting_fields(db_session, p.id, user_id="anyone")) == {
        "title", "job_name", "job_content", "certificates", "preferred", "major", "computer_skills",
    }
    assert get_posting_link(db_session, uuid.uuid4(), user_id="anyone") is None
