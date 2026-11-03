"""B12 자소서 PDF: 렌더링(개인정보 가림·연락처·줄바꿈) + API 흐름(권한·버전·저장·다운로드 토큰).

실제 PDF 변환(WeasyPrint)은 앱 이미지에 시스템 라이브러리·글꼴이 들어간 뒤 동작한다(D 반영 대기).
여기서는 변환만 대역으로 바꾸고 나머지 흐름을 그대로 검사한다.
"""
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.core.storage import objects
from app.features.pdf import render, service
from app.main import app

PHONE = "010-1234-5678"
FAKE_PDF = b"%PDF-1.7 fake"


def _plain(html: str) -> str:
    """태그를 걷어 낸 글자(낱말 단위 줄바꿈 상자 때문에 문구가 태그로 나뉜다)."""
    return re.sub(r"<[^>]+>", "", html)


def _as(sub):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub=sub)
    return TestClient(app)


@pytest.fixture
def stored(monkeypatch):
    """S3 대역: 저장한 객체를 기억하고 다운로드 때 돌려준다. 변환 대역: 넘겨받은 HTML을 기억."""
    bucket, htmls = {}, []
    monkeypatch.setattr(objects, "put_object", lambda key, data, ct: bucket.__setitem__(key, data))
    monkeypatch.setattr(objects, "open_object", lambda key: iter([bucket[key]]))
    monkeypatch.setattr(service, "render_pdf", lambda html: htmls.append(html) or FAKE_PDF)
    yield bucket, htmls
    app.dependency_overrides.clear()


def _resume(c, title="네이버 백엔드", bodies=(f"연락처 {PHONE} 로 주세요", "두 번째")):
    r = c.post("/resumes", json={"title": title}).json()
    qs = []
    for i, b in enumerate(bodies):
        q = c.post(f"/resumes/{r['id']}/questions", json={"title": f"문항{i}", "char_limit": 1000}).json()
        if b is not None:
            c.post(f"/resumes/{r['id']}/questions/{q['id']}/versions", json={"body": b})
        qs.append(q)
    return r, qs


# --- 렌더링 -------------------------------------------------------------------

def test_html_masks_tokens_keeps_contact_and_escapes():
    html = render.build_html("<제목>", [render.Item("지원 동기", "연락처 [[PHONE_1]] 입니다 <b>", 1000)],
                             render.Contact("홍길동", PHONE, "a@x.com"))
    assert "[[PHONE_1]]" not in html and "(전화번호 비공개)" in _plain(html), "본문 개인정보는 가림"
    assert f"홍길동 · {PHONE} · a@x.com" in html, "직접 입력한 연락처만 상단에"
    assert "&lt;제목&gt;" in html and "&lt;b&gt;" in html, "HTML 이스케이프"
    assert '<span class="w">연락처</span>' in html, "낱말 단위 줄바꿈(숨은 문자 없이 스타일로)"
    assert "⁠" not in html


def test_long_unbroken_word_is_not_kept_together():
    html = render.build_html("t", [render.Item("q", "1" * 40)])
    assert '<span class="w">' + "1" * 40 not in html, "띄어쓰기 없는 긴 글은 넘치지 않게 그대로"


def test_render_reports_unavailable_without_weasyprint(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_weasy(name, *a, **k):
        if name == "weasyprint":
            raise ImportError("no weasyprint")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_weasy)
    with pytest.raises(render.PdfUnavailable):
        render.render_pdf("<p>x</p>")


# --- API ----------------------------------------------------------------------

def test_export_latest_versions_stores_and_downloads_once(stored):
    bucket, htmls = stored
    owner = f"pdf-{uuid.uuid4()}"
    c = _as(owner)
    r, _ = _resume(c, bodies=(f"연락처 {PHONE} 로 주세요", None))
    res = c.post(f"/resumes/{r['id']}/pdf", json={"contact": {"name": "홍길동", "email": "a@x.com"}})
    assert res.status_code == 201, res.text
    out = res.json()
    assert out["filename"] == "네이버 백엔드.pdf" and out["download_path"].startswith("/downloads/")
    [key] = bucket
    assert key.startswith(f"users/{owner}/resumes/{r['id']}/") and key.endswith(".pdf")
    # 저장 본문의 개인정보는 복원하지 않는다
    assert PHONE not in htmls[0] and "(전화번호 비공개)" in _plain(htmls[0])
    assert "홍길동 · a@x.com" in htmls[0]
    assert "문항1" not in htmls[0], "내용 없는 문항은 넣지 않음"
    got = c.get(out["download_path"])
    assert got.status_code == 200 and got.content == FAKE_PDF
    assert got.headers["content-type"].startswith("application/pdf")
    assert c.get(out["download_path"]).status_code == 404, "1회용"


def test_export_chosen_older_version(stored):
    _, htmls = stored
    c = _as(f"pdf-{uuid.uuid4()}")
    r, qs = _resume(c, bodies=("첫 버전 본문", "다른 문항"))
    c.post(f"/resumes/{r['id']}/questions/{qs[0]['id']}/versions", json={"body": "두 번째 버전 본문"})
    old = c.get(f"/resumes/{r['id']}/questions/{qs[0]['id']}/versions").json()[-1]["id"]
    assert c.post(f"/resumes/{r['id']}/pdf", json={"version_ids": [old]}).status_code == 201
    text = _plain(htmls[0])
    assert "첫 버전 본문" in text and "두 번째 버전" not in text and "다른 문항" not in text


def test_export_rejections(stored):
    c = _as(f"pdf-{uuid.uuid4()}")
    r, _ = _resume(c)
    other, _ = _resume(c, title="다른 자소서")
    other_q = c.get(f"/resumes/{other['id']}").json()["questions"][0]
    foreign = other_q["latest_version"]["id"]
    assert c.post(f"/resumes/{r['id']}/pdf", json={"version_ids": [foreign]}).status_code == 422
    assert c.post(f"/resumes/{r['id']}/pdf", json={"contact": {"name": "900101-1234567"}}).status_code == 422
    empty, _ = _resume(c, title="빈 자소서", bodies=(None,))
    assert c.post(f"/resumes/{empty['id']}/pdf", json={}).status_code == 422
    stranger = _as(f"pdf-{uuid.uuid4()}")
    assert stranger.post(f"/resumes/{r['id']}/pdf", json={}).status_code == 404, "남의 자소서"


def test_export_returns_503_when_pdf_engine_missing(stored, monkeypatch):
    def unavailable(html):
        raise render.PdfUnavailable()
    monkeypatch.setattr(service, "render_pdf", unavailable)
    c = _as(f"pdf-{uuid.uuid4()}")
    r, _ = _resume(c)
    res = c.post(f"/resumes/{r['id']}/pdf", json={})
    assert res.status_code == 503 and res.json()["code"] == "pdf_unavailable"
