"""C14 — K-MOOC 강좌 수집 (공공데이터포털 apis.data.go.kr/B552881/kmooc_v2_0).

온라인 학습 콘텐츠 1순위 소스(약관 이용허락 제한없음·자동승인). courseList로 전량 카탈로그를 긁고
(list엔 키워드 검색이 없어 Page/Size로 전수), courseDetail로 **시간(est_hours)·요약·분류**를 보강한다.
파싱은 **순수 함수**(실 응답 모양 기준, 단위 테스트) / HTTP는 주입식 — C4 `collect.py`와 같은 결.

실 응답 확인(2026-10-23): list = {resultCode, resultMsg, totalCount, items[]}, detail.results =
{vod_playtime(초)·course_playtime(초)·week·classfy_name·middle_classfy_name·summary(HTML)·certificate_yn}.
est_hours = vod_playtime(실 영상 초) / 3600. summary는 HTML이라 태그 제거 후 매칭에 사용.
인증키는 `KMOOC_API_KEY`(env/Secrets, 커밋 금지), base는 `KMOOC_API_BASE_URL`(기본값 아래).
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime

KMOOC_SOURCE = "kmooc"
DEFAULT_BASE_URL = "https://apis.data.go.kr/B552881/kmooc_v2_0"
_SUCCESS = "00"
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class KmoocApiError(RuntimeError):
    """resultCode != '00' 또는 키 누락."""


@dataclass(frozen=True)
class KmoocCourse:
    """수집·매핑된 K-MOOC 강좌 1건(콘텐츠 모델 입력). detail 보강 전엔 아래 detail 필드가 None."""

    external_id: str
    title: str
    url: str
    provider: str | None = None
    rating: float | None = None
    public: bool = True
    auditor: bool = False          # 청강 가능 여부
    image: str | None = None
    enroll_start: date | None = None
    enroll_end: date | None = None
    study_start: date | None = None
    study_end: date | None = None
    # --- courseDetail 보강 ---
    est_hours: float | None = None      # vod_playtime(초)/3600 → 주차 배치 입력
    weeks: int | None = None
    summary: str | None = None          # HTML 제거한 평문(역량 매칭용)
    classfy: str | None = None          # 대분류 (예: 사회)
    middle_classfy: str | None = None   # 중분류 (예: 경영·경제)
    certificate: bool | None = None


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _yn(value) -> bool:
    return str(value).strip().upper() == "Y"


def epoch_to_date(value) -> date | None:
    """epoch 초(문자열/숫자) → UTC 날짜. 파싱 불가면 None."""
    sec = _as_int(value)
    if sec is None:
        return None
    try:
        return datetime.fromtimestamp(sec, tz=UTC).date()
    except (OverflowError, OSError, ValueError):
        return None


def seconds_to_hours(value) -> float | None:
    """초 → 시간(소수 1자리). 0 이하·파싱불가는 None."""
    sec = _as_int(value)
    if sec is None or sec <= 0:
        return None
    return round(sec / 3600, 1)


def strip_html(value: str | None) -> str:
    """태그 제거 + 엔티티 해제 + 공백 정리(summary 매칭용). 빈 입력은 ''"."""
    if not value:
        return ""
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", value))).strip()


def parse_list_item(raw: dict) -> KmoocCourse:
    """courseList items 한 건 → KmoocCourse(목록 수준 필드)."""
    return KmoocCourse(
        external_id=str(raw.get("id", "")).strip(),
        title=(raw.get("name") or "").strip(),
        url=(raw.get("url") or "").strip(),
        provider=(raw.get("org_name") or None),
        rating=_as_float(raw.get("rating")),
        public=_yn(raw.get("public_yn")),
        auditor=_yn(raw.get("is_auditor")),
        image=(raw.get("course_image") or None),
        enroll_start=epoch_to_date(raw.get("enrollment_start")),
        enroll_end=epoch_to_date(raw.get("enrollment_end")),
        study_start=epoch_to_date(raw.get("study_start")),
        study_end=epoch_to_date(raw.get("study_end")),
    )


def merge_detail(course: KmoocCourse, detail: dict) -> KmoocCourse:
    """courseDetail.results → 시간·주차·요약·분류·수료증 보강."""
    est = seconds_to_hours(detail.get("vod_playtime")) or seconds_to_hours(detail.get("course_playtime"))
    return replace(
        course,
        est_hours=est,
        weeks=_as_int(detail.get("week")),
        summary=(strip_html(detail.get("summary")) or None),
        classfy=(detail.get("classfy_name") or None),
        middle_classfy=(detail.get("middle_classfy_name") or None),
        certificate=_yn(detail.get("certificate_yn")),
    )


def _check(payload: dict) -> None:
    code = str(payload.get("resultCode", "")).strip()
    if code != _SUCCESS:
        raise KmoocApiError(f"K-MOOC resultCode={code}: {payload.get('resultMsg')}")


def parse_list_payload(payload: dict) -> tuple[list[KmoocCourse], int]:
    """courseList 응답 → (강좌들, totalCount). `items`는 단건이면 dict, 여러건이면 list."""
    _check(payload)
    items = payload.get("items")
    if items is None:
        rows: list[dict] = []
    elif isinstance(items, list):
        rows = items
    else:
        rows = [items]
    return [parse_list_item(r) for r in rows], (_as_int(payload.get("totalCount")) or 0)


def detail_results(payload: dict) -> dict:
    """courseDetail 응답 → results dict(단건이면 그대로, list면 첫 건)."""
    _check(payload)
    r = payload.get("results")
    if isinstance(r, list):
        return r[0] if r else {}
    return r or {}


def collect(
    fetch_list: Callable[[int, int], dict],
    fetch_detail: Callable[[str], dict] | None = None,
    *,
    page_size: int = 100,
    max_pages: int | None = None,
    public_only: bool = True,
) -> list[KmoocCourse]:
    """전량 수집: courseList 페이지네이션 → (선택) courseDetail 보강.

    `fetch_list(page, size)`·`fetch_detail(course_id)`는 주입(테스트는 가짜, 운영은 아래 HTTP).
    `public_only`면 `public_yn != 'Y'` 제외. totalCount만큼 모으면 종료(빈 페이지도 종료).
    """
    out: list[KmoocCourse] = []
    seen = 0
    total: int | None = None
    page = 1
    while max_pages is None or page <= max_pages:
        courses, tc = parse_list_payload(fetch_list(page, page_size))
        total = tc if total is None else total
        if not courses:
            break
        for course in courses:
            seen += 1
            if public_only and not course.public:
                continue
            if fetch_detail is not None:
                course = merge_detail(course, detail_results(fetch_detail(course.external_id)))
            out.append(course)
        if total and seen >= total:
            break
        page += 1
    return out


# --- 운영 HTTP (주입용 기본 구현; 네트워크라 단위 테스트 대상 아님) ------------------

def _base_url() -> str:
    return os.environ.get("KMOOC_API_BASE_URL", DEFAULT_BASE_URL)


def _api_key() -> str:
    key = os.environ.get("KMOOC_API_KEY")
    if not key:
        raise KmoocApiError("KMOOC_API_KEY env 필요 (로컬 .env / D Secrets)")
    return key


def _get(operation: str, params: dict) -> dict:
    query = urllib.parse.urlencode({"ServiceKey": _api_key(), **params})
    url = f"{_base_url()}/{operation}?{query}"
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 (https 고정 출처)
        return json.loads(resp.read().decode("utf-8"))


def fetch_list_page(page: int, size: int) -> dict:
    return _get("courseList_v2_0", {"Page": page, "Size": size})


def fetch_course_detail(course_id: str) -> dict:
    return _get("courseDetail_v2_0", {"CourseId": course_id})
