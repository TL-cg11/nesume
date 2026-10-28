"""C14 — 고용24 국민내일배움카드 훈련과정 수집 (`/cm/openApi/call/hr/callOpenApiSvcInfo310L01.do`).

학습 콘텐츠 오프라인(+원격) 소스. K-MOOC(`kmooc.py`)와 같은 결: 파싱은 **순수 함수**(실 응답 모양 기준,
단위 테스트) / HTTP는 주입식. 목록 API가 과정명 키워드 검색(`srchTraProcessNm`)을 지원하므로
**역량 키 → 검색어**(`KEYWORDS`)로 키워드별 수집하고, 그 키를 `competency_keys`로 붙인다.

실 응답 확인(2026-10-28, returnType=JSON): {srchList[], scn_cnt, pageNum, pageSize}.
오류도 HTTP 200 + 본문 `{"error": …}`로 온다 → 상태코드가 아니라 본문으로 판정한다.

보안·약관(docs/C14.md, 공유_타파트_정책실측출처.md 2.1절):
- **화이트리스트 매핑** — `telNo`(전화)·`titleIcon`(<img> HTML)·과정 상세의 `trprChap*`(담당자)는 읽지 않는다.
- 원문 링크 `titleLink`는 **https + work24.go.kr**만. 서버는 링크를 가져오지 않는다(표시용).
- 인증키(`WORK24_TRAINING_API_KEY`)는 쿼리스트링 `authKey`로 가므로 **예외에 URL을 싣지 않는다**.
- 저장은 서비스 화면 표시용으로만(약관 §17-3-③), 비영리(§11-2).
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta

WORK24_SOURCE = "work24"
DEFAULT_BASE_URL = "https://www.work24.go.kr"
LIST_PATH = "/cm/openApi/call/hr/callOpenApiSvcInfo310L01.do"
_ALLOWED_HOST = "work24.go.kr"
_MAX_BYTES = 5 * 1024 * 1024  # 응답 크기 상한(100건 JSON은 수백 KB)

#: 사전 밖이지만 수요가 큰 분야(초기 데모 키 유지)
_EXTRA_KEYWORDS: Mapping[str, str] = {"security": "정보보안", "network": "네트워크"}

#: 과정명에 한국어 표기가 흔한 것만 덮어쓴다. 나머지는 정식 이름(SQL·Docker …) — 사전 별칭은
#: "에스큐엘"·"씨샵" 같은 발음 표기라 과정명 검색어로 맞지 않는다.
_SEARCH_OVERRIDES: Mapping[str, str] = {
    "python": "파이썬",
    "java": "자바",
    "javascript": "자바스크립트",
    "linux": "리눅스",
    "aws": "클라우드",
}


def _search_term(term) -> str:
    return _SEARCH_OVERRIDES.get(term.key, term.canonical)


def build_keywords() -> dict[str, str]:
    """역량 키(**A11 사전 키** — 공고 갭과 같은 키) → 고용24 과정명 검색어. 사전 전 항목 + 추가 2개.

    키를 사전에서 만들어야 수집한 과정이 공고 갭과 바로 맞는다(docs/C14.md 강좌 역량 키 색인 3).
    """
    from app.features.matching.vocab import TERMS  # 지연 import(A11 사전)

    out = {t.key: _search_term(t) for t in TERMS}
    for k, v in _EXTRA_KEYWORDS.items():
        out.setdefault(k, v)
    return out


#: 기본 검색어 묶음(모듈 로드 시 1회). 테스트는 collect에 작은 dict를 직접 넘긴다.
KEYWORDS: Mapping[str, str] = build_keywords()
#: 수집 기간(오늘부터 개강 예정 과정). 이미 시작한 과정은 신청할 수 없어 뺀다.
DEFAULT_WINDOW_DAYS = 180


class Work24ApiError(RuntimeError):
    """본문 `error`·키 누락·요청 실패. 메시지에 요청 URL(인증키 포함)을 싣지 않는다."""


@dataclass(frozen=True)
class Work24Course:
    """수집·매핑된 훈련과정 1건(회차 단위). `LearningContent` 입력."""

    external_id: str            # trprId:trprDegr:trainstCstId (과정·회차·기관)
    title: str
    url: str                    # titleLink — https + work24.go.kr 검증됨
    mode: str                   # 원격훈련이면 online, 아니면 offline (결정 2)
    provider: str | None = None
    region: str | None = None   # address(시군구 수준)
    start: date | None = None
    end: date | None = None
    weeks: int | None = None    # 기간에서 계산(결정 4: est_hours는 비움)
    ncs_code: str | None = None
    rating: float | None = None  # stdgScor(만족도), 0은 미평가로 보고 None
    competency_keys: tuple[str, ...] = ()

    @property
    def classfy(self) -> str | None:
        """분류(매칭 보조) = NCS 세분류 코드 8자리(고용24 검색 브릿지, docs/C14.md 공통)."""
        return self.ncs_code

    @property
    def summary(self) -> str | None:
        """매칭·표시용 평문 — 기관·지역·기간 사실 정보만(기관이 쓴 설명문은 저장하지 않음)."""
        period = f"{self.start}~{self.end}" if self.start and self.end else None
        parts = [p for p in (self.provider, self.region, period) if p]
        return " · ".join(parts) or None


def _text(raw: Mapping, key: str) -> str:
    value = raw.get(key)
    return str(value).strip() if value is not None else ""


def _as_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _as_rating(value: str) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if score > 0 else None


def weeks_between(start: date | None, end: date | None) -> int | None:
    """기간(양끝 포함) → 주 수(올림). 날짜가 없거나 거꾸로면 None."""
    if start is None or end is None or end < start:
        return None
    return -(-((end - start).days + 1) // 7)


def is_allowed_link(url: str) -> bool:
    """원문 링크 허용: https + 호스트가 work24.go.kr 또는 그 하위 도메인."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == _ALLOWED_HOST or host.endswith("." + _ALLOWED_HOST))


def mode_of(train_target: str) -> str:
    """훈련 유형 → 학습 모드. `근로자원격훈련` 등 원격은 online(결정 2)."""
    return "online" if "원격" in train_target else "offline"


def parse_list_item(raw: Mapping) -> Work24Course | None:
    """srchList 한 건 → Work24Course. 식별자·제목·허용 링크가 없으면 None(적재 안 함).

    읽는 필드는 아래뿐이다(화이트리스트). `telNo`·`titleIcon` 등은 매핑 대상이 아니다.
    """
    ids = (_text(raw, "trprId"), _text(raw, "trprDegr"), _text(raw, "trainstCstId"))
    title, url = _text(raw, "title"), _text(raw, "titleLink")
    if not all(ids) or not title or not is_allowed_link(url):
        return None
    start, end = _as_date(_text(raw, "traStartDate")), _as_date(_text(raw, "traEndDate"))
    return Work24Course(
        external_id=":".join(ids),
        title=title,
        url=url,
        mode=mode_of(_text(raw, "trainTarget")),
        provider=_text(raw, "subTitle") or None,
        region=_text(raw, "address") or None,
        start=start,
        end=end,
        weeks=weeks_between(start, end),
        ncs_code=_text(raw, "ncsCd") or None,
        rating=_as_rating(_text(raw, "stdgScor")),
    )


def parse_list_payload(payload: object) -> tuple[list[Work24Course], int]:
    """목록 응답 → (과정들, 전체 건수 scn_cnt). 본문 `error`면 예외(오류를 데이터로 저장하지 않는다)."""
    if not isinstance(payload, Mapping):
        raise Work24ApiError("WORK24 응답 형식 오류")
    if "error" in payload:
        raise Work24ApiError(f"WORK24 error: {str(payload.get('error'))[:200]}")
    rows = payload.get("srchList") or []
    if isinstance(rows, Mapping):  # 단건이 dict로 올 가능성 대비
        rows = [rows]
    courses = [c for c in (parse_list_item(r) for r in rows if isinstance(r, Mapping)) if c is not None]
    try:
        total = int(payload.get("scn_cnt") or 0)
    except (TypeError, ValueError):
        total = 0
    return courses, total


def collect(
    fetch: Callable[[str, int, int], object],
    keywords: Mapping[str, str] = KEYWORDS,
    *,
    page_size: int = 100,
    max_pages: int = 2,
) -> list[Work24Course]:
    """키워드별 목록 수집 → 같은 과정(회차)은 하나로 합치고 역량 키를 합집합으로.

    `fetch(keyword, page, size)`는 주입(테스트는 가짜, 운영은 `fetch_list_page`). 키워드당 `max_pages`까지,
    `scn_cnt`만큼 받았거나 빈 페이지면 그 키워드는 종료. 호출 수 상한 = 키워드 수 × max_pages.
    """
    merged: dict[str, Work24Course] = {}
    for key, keyword in keywords.items():
        seen = 0
        for page in range(1, max_pages + 1):
            courses, total = parse_list_payload(fetch(keyword, page, page_size))
            for c in courses:
                prev = merged.get(c.external_id)
                keys = prev.competency_keys if prev else ()
                if key not in keys:
                    keys = (*keys, key)
                merged[c.external_id] = replace(c, competency_keys=keys)
            seen += page_size
            if not courses or seen >= total:
                break
    return list(merged.values())


# --- 운영 HTTP (주입용 기본 구현; 네트워크라 단위 테스트는 오류 처리만) ------------------

def _base_url() -> str:
    base = os.environ.get("WORK24_API_BASE_URL") or DEFAULT_BASE_URL
    if not base.startswith("https://"):
        raise Work24ApiError("WORK24_API_BASE_URL은 https여야 한다")
    return base.rstrip("/")


def _api_key() -> str:
    key = os.environ.get("WORK24_TRAINING_API_KEY")
    if not key:
        raise Work24ApiError("WORK24_TRAINING_API_KEY env 필요 (로컬 .env / D Secrets)")
    return key


def fetch_list_page(
    keyword: str, page: int, size: int, *, today: date | None = None, window_days: int = DEFAULT_WINDOW_DAYS
) -> object:
    """훈련과정 목록 1페이지(JSON). 오늘부터 `window_days` 안에 개강하는 과정만."""
    start = today or date.today()
    end = start + timedelta(days=window_days)
    query = urllib.parse.urlencode({
        "authKey": _api_key(),
        "returnType": "JSON",
        "outType": "1",
        "pageNum": page,
        "pageSize": size,
        "srchTraStDt": start.strftime("%Y%m%d"),
        "srchTraEndDt": end.strftime("%Y%m%d"),
        "srchTraProcessNm": keyword,
        "sort": "ASC",
        "sortCol": "TRNG_BGDE",
    })
    url = f"{_base_url()}{LIST_PATH}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 (https 고정 출처)
            body = resp.read(_MAX_BYTES + 1)
    except Exception as e:  # noqa: BLE001 - URL(인증키 포함)이 예외·로그에 남지 않게 바꿔 올린다
        raise Work24ApiError(f"WORK24 요청 실패: {type(e).__name__}") from None
    if len(body) > _MAX_BYTES:
        raise Work24ApiError("WORK24 응답 크기 초과")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise Work24ApiError("WORK24 응답이 JSON이 아님") from None
