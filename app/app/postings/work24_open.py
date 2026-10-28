"""C4 — 고용24 공채속보 수집 (목록 `210L21` → 공고별 상세 `210D21`, XML).

서울시 공고엔 원문 링크가 없어 추천에 링크를 붙일 수 없다 → 링크가 있는 공채속보를 두 번째 출처로
수집한다(docs/C4.md "공채속보 수집 + 추천 원문 링크 계획"). 서울시 파서(`collect.parse_seoul_row`)와
같은 결: 파싱은 **순수**(실 응답 모양 기준), HTTP는 주입식, 처리는 `collect.run_collection`이 묶는다.

- 식별: `empSeqno` → `source_key`(출처 고유 ID). `link_key`가 이걸 그대로 키로 쓴다.
- 원문 링크 `empWantedHomepgDetail`은 **기업별 외부 도메인**이라 도메인 제한 불가 → http/https만 저장.
  서버는 링크를 가져오지 않는다(표시용, SSRF 방어).
- **화이트리스트 매핑** — `inqryCont`(문의처·연락처)·`regLogImgNm`(http 로고)·자소서 문항은 읽지 않는다.
- XML: 크기 상한 + `<!DOCTYPE`/`<!ENTITY` 포함 시 거부 후 파싱. 오류도 HTTP 200 + `<error>`로 온다.
- 인증키(`WORK24_JOB_API_KEY`)는 쿼리스트링 `authKey` → 예외에 URL을 싣지 않는다.
- 약관: 고용24 Open API 약관(2024-11-18) — 비영리·화면 표시용 저장·재배포 금지
  (docs/공유_타파트_정책실측출처.md 2.1절).
"""
from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date
from typing import Any

SOURCE_WORK24_OPEN = "work24_open"
DEFAULT_BASE_URL = "https://www.work24.go.kr"
LIST_PATH = "/cm/openApi/call/wk/callOpenApiSvcInfo210L21.do"
DETAIL_PATH = "/cm/openApi/call/wk/callOpenApiSvcInfo210D21.do"
PAGE_SIZE = 100
_MAX_BYTES = 5 * 1024 * 1024
_FORBIDDEN_XML = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_YMD = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


class Work24OpenError(RuntimeError):
    """본문 `<error>`·형식 오류·요청 실패. 메시지에 요청 URL(인증키 포함)을 싣지 않는다."""


# ---- 파싱 (순수) -----------------------------------------------------------------

def parse_xml(body: bytes) -> ET.Element:
    """크기 상한·DTD/엔티티 거부 후 파싱. 본문 `<error>`면 예외."""
    if len(body) > _MAX_BYTES:
        raise Work24OpenError("공채속보 응답 크기 초과")
    if _FORBIDDEN_XML.search(body):
        raise Work24OpenError("공채속보 응답에 DTD/엔티티 선언 — 거부")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise Work24OpenError("공채속보 응답이 XML이 아님") from None
    if root.tag == "error" or root.find("error") is not None:
        msg = (root.text if root.tag == "error" else root.findtext("error")) or ""
        raise Work24OpenError(f"공채속보 error: {msg.strip()[:200]}")
    return root


def _text(node: ET.Element | None, tag: str) -> str | None:
    if node is None:
        return None
    value = node.findtext(tag)
    value = value.strip() if value else ""
    return value or None


def _ymd(value: str | None) -> date | None:
    m = _YMD.match(value or "")
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def safe_link(url: str | None) -> str | None:
    """원문 링크는 http/https만(기업별 외부 도메인이라 도메인 제한은 불가). 아니면 None."""
    if not url:
        return None
    try:
        parsed = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return url.strip()


def parse_list(root: ET.Element) -> tuple[list[str], int]:
    """목록 → (empSeqno 목록, 전체 건수)."""
    seqnos = [s for s in (_text(n, "empSeqno") for n in root.iter("dhsOpenEmpInfo")) if s]
    try:
        total = int(root.findtext("total") or 0)
    except ValueError:
        total = 0
    return seqnos, total


def _first_job(root: ET.Element) -> tuple[str | None, str | None]:
    """모집 직종 목록 중 첫 건(코드, 이름). 코드는 6자리만."""
    for info in root.iter("empJobsListInfo"):
        code, name = _text(info, "jobsCd"), _text(info, "jobsCdKorNm")
        if code or name:
            return (code if code and len(code) <= 6 else None), name
    return None, None


def _join(*parts: str | None) -> str | None:
    text = "\n\n".join(p for p in parts if p)
    return text or None


def _recruit_lines(root: ET.Element) -> str | None:
    """모집분야별 '분야: 직무내용' 줄(분야가 여럿일 수 있음)."""
    lines = []
    for info in root.iter("empRecrListInfo"):
        name, cont = _text(info, "empRecrNm"), _text(info, "jobCont")
        if name or cont:
            lines.append(f"{name}: {cont}" if name and cont else (name or cont))
    return "\n".join(lines) or None


def parse_detail(root: ET.Element) -> dict[str, Any]:
    """상세 → `JobPosting` 필드 dict(순수). 읽는 태그는 아래뿐(화이트리스트)."""
    node = root if root.find("empSeqno") is not None else root.find(".//dhsOpenEmpInfoDetailRoot")
    if node is None:
        node = root
    job_code, job_name = _first_job(root)
    recr = next(iter(root.iter("empRecrListInfo")), None)
    end = _ymd(_text(node, "empWantedEndt"))
    return {
        "source_key": _text(node, "empSeqno"),
        "company_name": _text(node, "empBusiNm"),
        "title": _text(node, "empWantedTitle"),
        "job_code": job_code,
        "job_name": job_name,
        "industry_name": _text(node, "coClcdNm"),  # 기업 구분(대기업·공공기관 등)
        "region_name": _text(recr, "workRegionNm") or _text(node, "workRegionNm"),
        "emp_type_text": _text(node, "empWantedTypeNm"),
        "job_content": _join(  # 모집분야·직무 + 지원자격 + 요약(A1 mask는 run_collection이 적용)
            _recruit_lines(root),
            _text(node, "recrCommCont"),
            _text(node, "empnRecrSummaryCont"),
        ),
        "certificates": _text(recr, "sptCertEtc") or _text(node, "sptCertEtc"),
        "apply_method": _text(node, "empRcptMthdCont"),
        "required_docs": _text(node, "empSubmitDocCont"),
        "registered_on": _ymd(_text(node, "empWantedStdt")),
        "close_text": _text(node, "empWantedEndt"),
        "closes_on": end,
        "until_filled": False,
        # 공고 상세 링크 우선, 불량·없으면 기업 채용 홈페이지
        "source_url": (
            safe_link(_text(node, "empWantedHomepgDetail")) or safe_link(_text(node, "empWantedHomepg"))
        ),
    }


# ---- 수집 (주입식) -----------------------------------------------------------------

def fetch_all(
    fetch: Callable[[str, dict[str, Any]], bytes],
    *,
    page_size: int = PAGE_SIZE,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    """목록 전량 → 공고별 상세 → 필드 dict 목록. `fetch(path, params)`는 주입(운영은 `http_fetch`).

    호출 수 상한 = max_pages + 공고 수(현재 ~330/일, 1일 1만 상한 내).
    """
    seqnos: list[str] = []
    for page in range(1, max_pages + 1):
        params = {"callTp": "L", "startPage": page, "display": page_size}
        found, total = parse_list(parse_xml(fetch(LIST_PATH, params)))
        seqnos.extend(s for s in found if s not in seqnos)
        if not found or len(seqnos) >= total:
            break
    rows = []
    for seq in seqnos:
        fields = parse_detail(parse_xml(fetch(DETAIL_PATH, {"callTp": "D", "empSeqno": seq})))
        if fields.get("source_key") and fields.get("title"):
            rows.append(fields)
    return rows


def http_fetch(path: str, params: dict[str, Any]) -> bytes:
    """운영 HTTP(https 고정). 키·주소는 env(D Secrets)."""
    base = (os.environ.get("WORK24_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    if not base.startswith("https://"):
        raise Work24OpenError("WORK24_API_BASE_URL은 https여야 한다")
    key = os.environ.get("WORK24_JOB_API_KEY")
    if not key:
        raise Work24OpenError("WORK24_JOB_API_KEY env 필요 (로컬 .env / D Secrets)")
    query = urllib.parse.urlencode({"authKey": key, "returnType": "XML", **params})
    try:
        with urllib.request.urlopen(f"{base}{path}?{query}", timeout=30) as resp:  # noqa: S310 (https 고정 출처)
            return resp.read(_MAX_BYTES + 1)
    except Exception as e:  # noqa: BLE001 - URL(인증키 포함)이 예외·로그에 남지 않게 바꿔 올린다
        raise Work24OpenError(f"공채속보 요청 실패: {type(e).__name__}") from None
