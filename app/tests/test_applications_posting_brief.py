"""C15 카드 공고 요약: 원문 주소(source_url → url). DB 불필요(순수)."""
import uuid
from datetime import date
from types import SimpleNamespace

from app.features.applications.schemas import PostingBrief


def _posting(source_url):
    return SimpleNamespace(
        id=uuid.uuid4(), company_name="회사", title="보안 엔지니어", region_name="서울",
        closes_on=date(2026, 11, 2), is_active=True, source_url=source_url,
    )


def test_posting_brief_exposes_source_url_as_url():
    out = PostingBrief.model_validate(_posting("https://www.work24.go.kr/x")).model_dump()
    assert out["url"] == "https://www.work24.go.kr/x"
    assert out["closes_on"] == date(2026, 11, 2)
    assert "source_url" not in out


def test_posting_brief_url_none_when_missing():  # 서울시 공고 등
    assert PostingBrief.model_validate(_posting(None)).url is None
