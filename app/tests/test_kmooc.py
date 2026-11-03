"""C14 K-MOOC 수집 파서 테스트. 실제 응답 모양(2026-10-23) 기준·순수(네트워크 없음)."""
import datetime
import io
import urllib.error

import pytest

from app.features.roadmap import kmooc as _km
from app.features.roadmap.kmooc import (
    KmoocApiError,
    collect,
    detail_results,
    epoch_to_date,
    merge_detail,
    parse_list_item,
    parse_list_payload,
    seconds_to_hours,
    strip_html,
)

# 실제 courseList item (금융감독원 강좌)
_LIST_ITEM = {
    "id": "21435", "name": "실용금융의 이론과 실제", "url": "https://www.kmooc.kr/view/course/detail/21435",
    "org_name": "금융감독원", "rating": 4.6, "public_yn": "Y", "is_auditor": "N",
    "course_image": "https://lms.kmooc.kr/course/thumb.php?id=21435",
    "enrollment_start": "1792940400", "study_start": "1793545200",
}
# 실제 courseDetail results 일부
_DETAIL = {
    "vod_playtime": 47674, "course_playtime": 108000, "week": "15",
    "classfy_name": "사회", "middle_classfy_name": "경영 · 경제", "certificate_yn": "Y",
    "summary": "<div><h2>강좌 소개</h2><p>금융상품과 금융시장을 살펴봅니다.</p></div>",
}


def test_parse_list_item_maps_real_fields():
    c = parse_list_item(_LIST_ITEM)
    assert c.external_id == "21435"
    assert c.title == "실용금융의 이론과 실제"
    assert c.url.endswith("/21435")
    assert c.provider == "금융감독원"
    assert c.rating == 4.6
    assert c.public is True and c.auditor is False
    assert c.study_start == datetime.date(2026, 11, 1)  # epoch → UTC date
    assert c.est_hours is None  # detail 전


def test_merge_detail_uses_vod_playtime_hours():
    c = merge_detail(parse_list_item(_LIST_ITEM), _DETAIL)
    assert c.est_hours == round(47674 / 3600, 1)  # 13.2h (vod_playtime 우선)
    assert c.weeks == 15
    assert c.classfy == "사회" and c.middle_classfy == "경영 · 경제"
    assert c.certificate is True
    assert "금융상품과 금융시장" in c.summary and "<" not in c.summary  # HTML 제거


def test_seconds_to_hours_and_epoch():
    assert seconds_to_hours(47674) == 13.2
    assert seconds_to_hours(0) is None and seconds_to_hours("x") is None
    assert epoch_to_date("1793545200") == datetime.date(2026, 11, 1)
    assert epoch_to_date("") is None


def test_strip_html():
    assert strip_html("<p>A  &amp; <b>B</b></p>") == "A & B"
    assert strip_html(None) == ""


def test_parse_list_payload_items_dict_or_list():
    # 여러 건 = list
    many = {"resultCode": "00", "totalCount": "2", "items": [_LIST_ITEM, _LIST_ITEM]}
    rows, total = parse_list_payload(many)
    assert len(rows) == 2 and total == 2
    # 단건 = dict
    one = {"resultCode": "00", "totalCount": "1", "items": _LIST_ITEM}
    rows, _ = parse_list_payload(one)
    assert len(rows) == 1 and rows[0].external_id == "21435"


def test_payload_error_raises():
    with pytest.raises(KmoocApiError):
        parse_list_payload({"resultCode": "20", "resultMsg": "SERVICE_KEY_IS_NULL"})
    with pytest.raises(KmoocApiError):
        detail_results({"resultCode": "10", "resultMsg": "bad"})


def test_detail_results_list_or_dict():
    assert detail_results({"resultCode": "00", "results": _DETAIL})["week"] == "15"
    assert detail_results({"resultCode": "00", "results": [_DETAIL]})["week"] == "15"
    assert detail_results({"resultCode": "00", "results": None}) == {}


def test_collect_paginates_and_boosts_detail():
    pages = {
        1: {"resultCode": "00", "totalCount": "3", "items": [
            dict(_LIST_ITEM, id="1"), dict(_LIST_ITEM, id="2", public_yn="N")]},
        2: {"resultCode": "00", "totalCount": "3", "items": dict(_LIST_ITEM, id="3")},
    }
    calls = []

    def fake_list(page, size):
        return pages[page]

    def fake_detail(cid):
        calls.append(cid)
        return {"resultCode": "00", "results": _DETAIL}

    got = collect(fake_list, fake_detail, page_size=2)
    # public_yn='N'(id=2) 제외 → id 1, 3
    assert [c.external_id for c in got] == ["1", "3"]
    assert all(c.est_hours == 13.2 for c in got)  # detail 보강됨
    assert calls == ["1", "3"]  # 비공개엔 detail 호출 안 함


def test_collect_public_only_false_keeps_all():
    page = {"resultCode": "00", "totalCount": "2", "items": [
        dict(_LIST_ITEM, id="1"), dict(_LIST_ITEM, id="2", public_yn="N")]}
    got = collect(lambda p, s: page, public_only=False, max_pages=1)
    assert [c.external_id for c in got] == ["1", "2"]


# --- HTTP 재시도·키 숨김 (docs/C14.md K-MOOC 수집 503 실패) ---

_SECRET = "SECRET-KMOOC-KEY-123"  # gitleaks:allow — 가짜 표식(예외에 키가 안 실리는지 확인용)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code):
    url = f"https://apis.data.go.kr/x?ServiceKey={_SECRET}"
    return urllib.error.HTTPError(url, code, "err", {}, None)


def _patch(monkeypatch, outcomes):
    monkeypatch.setenv("KMOOC_API_KEY", _SECRET)
    calls, sleeps = [], []

    def fake_urlopen(url, timeout):
        calls.append(url)
        out = outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return _Resp(out)

    monkeypatch.setattr(_km.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(_km, "_sleep", sleeps.append)
    return calls, sleeps


def test_retries_5xx_then_succeeds(monkeypatch):
    calls, sleeps = _patch(monkeypatch, [_http_error(503), TimeoutError(), b'{"resultCode": "00"}'])
    assert _km.fetch_list_page(1, 100) == {"resultCode": "00"}
    assert len(calls) == 3 and sleeps == [1.0, 2.0]


def test_4xx_not_retried(monkeypatch):
    calls, sleeps = _patch(monkeypatch, [_http_error(401)])
    with pytest.raises(_km.KmoocApiError, match="HTTP 401"):
        _km.fetch_list_page(1, 100)
    assert len(calls) == 1 and sleeps == []


def test_gives_up_and_hides_key(monkeypatch):
    calls, _ = _patch(monkeypatch, [_http_error(503)] * 4)
    with pytest.raises(_km.KmoocApiError) as ei:
        _km.fetch_course_detail("c1")
    assert len(calls) == 4
    err = ei.value
    assert _SECRET not in str(err) and _SECRET not in repr(err)
    assert err.__cause__ is None and err.__suppress_context__  # 원래 HTTPError(URL 보유)가 안 딸려 감


def test_oversized_and_non_json_rejected(monkeypatch):
    _patch(monkeypatch, [b"x" * (_km._MAX_BYTES + 1)])
    with pytest.raises(_km.KmoocApiError, match="크기"):
        _km.fetch_list_page(1, 100)
    _patch(monkeypatch, [b"<html>"])
    with pytest.raises(_km.KmoocApiError, match="JSON"):
        _km.fetch_list_page(1, 100)
