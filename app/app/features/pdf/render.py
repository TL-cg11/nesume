"""B12 자소서 PDF 렌더링(spec 3.2): HTML → PDF(WeasyPrint).

템플릿은 '기본' 하나(10/30 사용자 결정 — tasks B12의 기본·간결·표 3종 중 기본만, part2_guide 4.69).

- 본문의 개인정보 토큰(`[[PHONE_1]]`)은 복원하지 않고 '(전화번호 비공개)'처럼 가려서 출력한다
  (spec 3.2, 10/30 결정).
  제출용 연락처는 PDF를 만들 때 사용자가 직접 입력한 값만 상단에 넣는다(저장하지 않음).
- 글꼴은 이미지에 설치한 나눔고딕(fonts-nanum). 한글이 깨지지 않도록 모든 템플릿이 같은 글꼴 묶음을 쓴다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape

from app.features.share.display import readable

_BASE_CSS = """
@page { size: A4; margin: 20mm 18mm 18mm; @bottom-center { content: counter(page) " / " counter(pages);
  font-family: "NanumGothic", sans-serif; font-size: 8.5pt; color: #8a94a0; } }
* { box-sizing: border-box; }
body { font-family: "NanumGothic", "Noto Sans CJK KR", sans-serif; color: #1b2032; font-size: 10.5pt;
  line-height: 1.75; word-break: keep-all; overflow-wrap: break-word; }  /* 한글은 낱말 단위로 줄바꿈 */
h1 { margin: 0; font-size: 18pt; letter-spacing: -0.2pt; }
.contact { margin-top: 4pt; color: #5f6e7a; font-size: 9.5pt; }
.body { white-space: pre-wrap; }
.body .w { white-space: nowrap; }
.meta { color: #8a94a0; font-size: 8.5pt; font-weight: normal; }
"""

_CSS = _BASE_CSS + """
header { padding-bottom: 10pt; border-bottom: 2pt solid #1b2032; margin-bottom: 14pt; }
section { margin-bottom: 16pt; padding-bottom: 14pt; border-bottom: 0.6pt solid #dce3e7; }
section:last-child { border-bottom: 0; }
h2 { margin: 0 0 6pt; font-size: 12pt; }
.body { line-height: 1.85; }
"""


@dataclass(frozen=True)
class Contact:
    name: str = ""
    phone: str = ""
    email: str = ""

    def line(self) -> str:
        return " · ".join(x for x in (self.name, self.phone, self.email) if x.strip())


@dataclass(frozen=True)
class Item:
    title: str
    body: str  # 저장된 본문(개인정보 토큰 상태)
    char_limit: int | None = None


_WORD = re.compile(r"\S+")
KEEP_WORD_MAX = 30  # 이보다 긴 낱말(띄어쓰기 없는 긴 글)은 넘치지 않게 그대로 둔다


def _text(raw: str) -> str:
    """본문 표시: 개인정보 토큰은 가리고, 한글이 낱말 중간에서 끊기지 않게 낱말을 줄바꿈 금지 상자로 감싼다.

    WeasyPrint는 word-break: keep-all을 지원하지 않는다. 보이지 않는 문자(U+2060)를 넣으면 PDF에서 복사한 글에
    딸려 가 지원서 글자 수가 달라질 수 있어, 글자는 그대로 두고 스타일(white-space: nowrap)로만 막는다.
    """
    def keep(m: re.Match) -> str:
        w = m.group(0)
        return f'<span class="w">{escape(w)}</span>' if len(w) <= KEEP_WORD_MAX else escape(w)
    return _WORD.sub(keep, readable(raw))


def _meta(item: Item) -> str:
    n = len(readable(item.body))
    return f"{n:,}자" + (f" / {item.char_limit:,}자" if item.char_limit else "")


def build_html(resume_title: str, items: list[Item], contact: Contact = Contact()) -> str:
    head = f"<header><h1>{escape(resume_title)}</h1>"
    if contact.line():
        head += f'<div class="contact">{escape(contact.line())}</div>'
    head += "</header>"
    main = "".join(
        f"<section><h2>{escape(it.title)} <span class=\"meta\">{_meta(it)}</span></h2>"
        f"<div class=\"body\">{_text(it.body)}</div></section>"
        for it in items
    )
    title = escape(resume_title)
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{title}</title>'
            f"<style>{_CSS}</style></head><body>{head}{main}</body></html>")


class PdfUnavailable(RuntimeError):
    """앱 이미지에 WeasyPrint(시스템 라이브러리·글꼴 포함)가 없다 — D의 이미지 반영 전."""


def render_pdf(html: str) -> bytes:
    try:
        from weasyprint import HTML  # 무거운 의존성이라 실제 변환 때만 불러온다
    except (ImportError, OSError) as e:  # OSError: pango 등 시스템 라이브러리 없음
        raise PdfUnavailable() from e
    return HTML(string=html).write_pdf()
