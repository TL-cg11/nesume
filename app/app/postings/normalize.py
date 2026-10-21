"""C4 — 공고 식별용 정규화 (link_key·content_hash 입력 안정화).

같은 공고가 수집마다 미세하게 다른 문자열로 와도 같은 키가 나오도록,
기업명·제목·지역·직종코드를 일관된 형태로 깎는다. **식별 정확도의 급소**
(docs/C4.md: 공수의 대부분은 키 구성이 아니라 정규화).

규칙: NFKC 정규화(전각→반각, ㈜→(주) 등) → casefold → 한글·영숫자만 남기고
      나머지는 구분 공백으로 축소. 기업명은 법인 형태 표기를 먼저 제거.

순수 stdlib(re, unicodedata). DB·외부 의존 없음.
"""
from __future__ import annotations

import re
import unicodedata

# 법인 형태 표기 — 식별엔 무의미하고 표기만 흔들림(㈜/(주)/주식회사 …) → 제거.
# NFKC 후 비교하므로 ㈜(U+321C)는 이미 "(주)"로 펼쳐진 상태로 들어온다.
_CORP_FORMS: tuple[str, ...] = (
    "주식회사", "유한회사", "유한책임회사", "합자회사", "합명회사",
    "재단법인", "사단법인", "사회복지법인", "의료법인", "학교법인", "법인",
    "(주)", "(유)", "(재)", "(사)",
)

# 한글(완성형)·영문 소문자·숫자만 식별 기준으로 남긴다.
_KEEP = re.compile(r"[^0-9a-z가-힣]+")


def _nfkc_fold(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def normalize_company(name: str | None) -> str:
    """기업명 정규화. 법인 형태 표기 제거 후 식별 문자만 남긴다."""
    if not name:
        return ""
    t = _nfkc_fold(name)
    for form in _CORP_FORMS:
        t = t.replace(form.casefold(), " ")
    return _KEEP.sub(" ", t).strip()


def normalize_title(title: str | None) -> str:
    """제목 정규화. 공백·기호 차이를 없애 같은 모집 제목이 같은 키가 되도록."""
    if not title:
        return ""
    return _KEEP.sub(" ", _nfkc_fold(title)).strip()


def normalize_code(code: str | None) -> str:
    """지역·직종 코드 정규화. 코드값만 남긴다(공백·구분자 제거)."""
    if not code:
        return ""
    return re.sub(r"[^0-9a-z]", "", _nfkc_fold(code))
