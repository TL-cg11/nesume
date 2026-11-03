"""C14 고용24 훈련과정 수집 테스트. 파서는 실제 응답 모양(2026-10-28, JSON) 기준·순수(네트워크 없음),
적재(`upsert_contents`)는 DB 필요(conftest `db_session`).
"""
import datetime
import urllib.error

import pytest
from sqlalchemy import select

from app.features.roadmap import work24
from app.features.roadmap.service import upsert_contents
from app.features.roadmap.work24 import (
    WORK24_SOURCE,
    Work24ApiError,
    collect,
    is_allowed_link,
    parse_list_item,
    parse_list_payload,
    weeks_between,
)
from app.models.learning import LearningContent

# 실제 srchList 한 건(2026-10-28 "클라우드" 검색). telNo·titleIcon은 실제 응답에 있는 그대로 둔다.
_ITEM = {
    "title": "[ICT 지식 큐브] 인공지능, 보안, 네트워크, 클라우드",
    "titleLink": "https://www.work24.go.kr/hr/a/a/3100/selectTracseDetl.do?tracseId=ACG20263001201126&tracseTme=243",
    "subTitle": "(1st)인비원 평생교육원",
    "subTitleLink": "https://www.work24.go.kr/hr/a/a/3200/selectTrainInstitution.do",
    "titleIcon": '<img src="hrd.work24.go.kr/images/ico_system13.gif" alt="근로자직업능력개발훈련">',
    "telNo": "070-4242-2990",
    "trprId": "ACG20263001201126",
    "trprDegr": "243",
    "trainstCstId": "500044312625",
    "ncsCd": "20010102",
    "traStartDate": "2026-11-01",
    "traEndDate": "2026-12-01",
    "address": "경기 고양시 일산동구",
    "trainTarget": "근로자원격훈련",
    "realMan": "74250",
    "stdgScor": "0",
    "contents": "",
}


def _item(**over):
    return {**_ITEM, **over}


def _payload(items, total=None):
    count = len(items) if total is None else total
    return {"srchList": items, "scn_cnt": count, "pageNum": "1", "pageSize": "100"}


# --------------------------------------------------------------------------
# 파서 (순수)
# --------------------------------------------------------------------------

def test_parse_list_item_maps_real_fields():
    c = parse_list_item(_ITEM)
    assert c.external_id == "ACG20263001201126:243:500044312625"
    assert c.title.startswith("[ICT 지식 큐브]")
    assert c.url == _ITEM["titleLink"]
    assert c.provider == "(1st)인비원 평생교육원"
    assert c.start == datetime.date(2026, 11, 1) and c.end == datetime.date(2026, 12, 1)
    assert c.weeks == 5  # 31일 → 5주(올림)
    assert c.classfy == "20010102"  # NCS 세분류
    assert c.rating is None  # stdgScor "0" = 미평가
    assert c.summary == "(1st)인비원 평생교육원 · 경기 고양시 일산동구 · 2026-11-01~2026-12-01"


def test_parse_drops_pii_and_html_fields():
    """telNo(전화)·titleIcon(<img>)은 어디에도 실리지 않는다(화이트리스트 매핑)."""
    c = parse_list_item(_ITEM)
    dumped = repr(c) + (c.summary or "")
    assert "070-4242-2990" not in dumped
    assert "<img" not in dumped


@pytest.mark.parametrize(
    ("target", "mode"),
    [("근로자원격훈련", "online"), ("국민내일배움카드(일반)", "offline"), ("", "offline")],
)
def test_mode_remote_is_online(target, mode):
    assert parse_list_item(_item(trainTarget=target)).mode == mode


@pytest.mark.parametrize(
    "url",
    [
        "http://www.work24.go.kr/hr/a.do",          # https 아님
        "https://evil.example.com/work24.go.kr",    # 다른 호스트
        "https://work24.go.kr.evil.com/x",          # 접미 위장
        "javascript:alert(1)",
        "",
    ],
)
def test_disallowed_link_is_skipped(url):
    assert not is_allowed_link(url)
    assert parse_list_item(_item(titleLink=url)) is None


def test_allowed_links():
    assert is_allowed_link("https://www.work24.go.kr/hr/a.do")
    assert is_allowed_link("https://work24.go.kr/x")


@pytest.mark.parametrize("missing", ["trprId", "trprDegr", "trainstCstId", "title"])
def test_missing_id_or_title_is_skipped(missing):
    assert parse_list_item(_item(**{missing: ""})) is None


def test_weeks_between():
    d = datetime.date
    assert weeks_between(d(2026, 11, 1), d(2026, 11, 7)) == 1
    assert weeks_between(d(2026, 11, 1), d(2026, 11, 8)) == 2
    assert weeks_between(d(2026, 11, 2), d(2026, 11, 1)) is None
    assert weeks_between(None, d(2026, 11, 1)) is None


def test_error_body_raises():
    """오류도 HTTP 200 + {"error": …} — 데이터로 저장하지 않고 예외."""
    with pytest.raises(Work24ApiError):
        parse_list_payload({"error": "인증키가 유효하지 않습니다"})
    with pytest.raises(Work24ApiError):
        parse_list_payload(["not", "a", "dict"])


def test_payload_parses_and_filters_invalid():
    courses, total = parse_list_payload(_payload([_ITEM, _item(titleLink="http://x")], total=380))
    assert [c.external_id for c in courses] == ["ACG20263001201126:243:500044312625"]
    assert total == 380


# --------------------------------------------------------------------------
# collect (키워드별 수집·중복 병합·종료)
# --------------------------------------------------------------------------

def test_collect_merges_same_course_across_keywords():
    """같은 과정이 두 키워드에 걸리면 1건, 역량 키는 합집합."""
    other = _item(trprId="AIG2026000000001", title="파이썬 기초")

    def fetch(keyword, page, size):
        return _payload({"클라우드": [_ITEM], "정보보안": [_ITEM, other]}[keyword])

    got = {c.external_id: c for c in collect(fetch, {"aws": "클라우드", "security": "정보보안"})}
    assert len(got) == 2
    assert got["ACG20263001201126:243:500044312625"].competency_keys == ("aws", "security")
    assert got["AIG2026000000001:243:500044312625"].competency_keys == ("security",)


def test_collect_pages_until_total_and_caps_calls():
    calls = []

    def fetch(keyword, page, size):
        calls.append(page)
        return _payload([_item(trprDegr=str(page))], total=1000)  # 전체는 많지만

    collect(fetch, {"aws": "클라우드"}, page_size=1, max_pages=2)
    assert calls == [1, 2]  # max_pages 상한


def test_collect_stops_on_empty_page():
    calls = []

    def fetch(keyword, page, size):
        calls.append(page)
        return _payload([], total=0)

    assert collect(fetch, {"aws": "클라우드"}, max_pages=5) == []
    assert calls == [1]


def test_collect_propagates_api_error():
    with pytest.raises(Work24ApiError):
        collect(lambda *_: {"error": "x"}, {"aws": "클라우드"})


# --------------------------------------------------------------------------
# HTTP 오류 처리 — 인증키가 예외 메시지에 실리지 않는다
# --------------------------------------------------------------------------

def test_fetch_error_hides_url_and_key(monkeypatch):
    secret = "SECRET-KEY-123"
    monkeypatch.setenv("WORK24_TRAINING_API_KEY", secret)
    monkeypatch.setenv("WORK24_API_BASE_URL", "https://www.work24.go.kr")

    def boom(url, timeout):
        raise urllib.error.HTTPError(url, 500, "err", {}, None)

    monkeypatch.setattr(work24.urllib.request, "urlopen", boom)
    with pytest.raises(Work24ApiError) as ei:
        work24.fetch_list_page("클라우드", 1, 10)
    assert secret not in str(ei.value)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__  # 원 예외(URL 포함) 체인 끊음


def test_fetch_requires_https_base_and_key(monkeypatch):
    monkeypatch.setenv("WORK24_TRAINING_API_KEY", "k")
    monkeypatch.setenv("WORK24_API_BASE_URL", "http://www.work24.go.kr")
    with pytest.raises(Work24ApiError):
        work24.fetch_list_page("클라우드", 1, 10)
    monkeypatch.delenv("WORK24_TRAINING_API_KEY")
    monkeypatch.setenv("WORK24_API_BASE_URL", "https://www.work24.go.kr")
    with pytest.raises(Work24ApiError):
        work24.fetch_list_page("클라우드", 1, 10)


# --------------------------------------------------------------------------
# 적재 (DB)
# --------------------------------------------------------------------------

def _rows(session):
    return session.execute(
        select(LearningContent).where(LearningContent.source == WORK24_SOURCE)
    ).scalars().all()


def test_upsert_work24_inserts_with_mode_and_keys(db_session):
    onsite_raw = _item(trprId="AIG2026000000009", trainTarget="국민내일배움카드(일반)")
    remote, onsite = parse_list_item(_ITEM), parse_list_item(onsite_raw)
    courses = collect(lambda *_: _payload([_ITEM, onsite_raw]), {"aws": "클라우드"})

    counts = upsert_contents(db_session, courses, source=WORK24_SOURCE, mode="offline")
    db_session.flush()

    assert counts == {"inserted": 2, "updated": 0, "skipped": 0}
    by_id = {r.external_id: r for r in _rows(db_session)}
    assert by_id[remote.external_id].mode == "online"     # 원격
    assert by_id[onsite.external_id].mode == "offline"
    assert by_id[remote.external_id].competency_keys == ["aws"]
    assert by_id[remote.external_id].weeks == 5
    assert by_id[remote.external_id].est_hours is None    # 결정 4
    assert "070-4242-2990" not in (by_id[remote.external_id].summary or "")


def test_upsert_work24_merges_keys_on_update(db_session):
    first = collect(lambda *_: _payload([_ITEM]), {"aws": "클라우드"})
    upsert_contents(db_session, first, source=WORK24_SOURCE)
    db_session.flush()
    second = collect(lambda *_: _payload([_item(title="제목 변경")]), {"security": "정보보안"})
    counts = upsert_contents(db_session, second, source=WORK24_SOURCE)
    db_session.flush()

    (row,) = _rows(db_session)
    assert counts["updated"] == 1
    assert row.title == "제목 변경"
    assert row.competency_keys == ["aws", "security"]  # 기존 키 유지 + 합집합


def test_upsert_default_source_is_kmooc_and_keeps_keys(db_session):
    """기존 K-MOOC 호출(source 미지정)은 그대로: source=kmooc, competency_keys 안 건드림."""
    from app.features.roadmap.kmooc import parse_list_item as kmooc_item

    k = kmooc_item({"id": "21435", "name": "실용금융", "url": "https://www.kmooc.kr/view/course/detail/21435",
                    "public_yn": "Y"})
    upsert_contents(db_session, [k])
    db_session.flush()
    row = db_session.execute(
        select(LearningContent).where(LearningContent.external_id == "21435")
    ).scalars().one()
    row.competency_keys = ["finance"]
    db_session.flush()

    upsert_contents(db_session, [k])
    db_session.flush()
    assert row.source == "kmooc" and row.mode == "online"
    assert row.competency_keys == ["finance"]
