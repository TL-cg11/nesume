"""C14 K-MOOC 수집 파서 테스트. 실제 응답 모양(2026-10-23) 기준·순수(네트워크 없음)."""
import datetime

import pytest

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
