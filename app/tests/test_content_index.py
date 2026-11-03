"""C14 강좌 역량 키 색인 테스트 — A11 사전 색인·고용24 검색어·대체 제목 검색·K-MOOC 배치.

순수(색인·단어 추출·검색어)와 DB(conftest `db_session`) 혼합.
"""
import pytest
from sqlalchemy import select

from app.features.roadmap import kmooc
from app.features.roadmap.kmooc import KmoocCourse
from app.features.roadmap.service import (
    _like_escape,
    build_roadmap,
    fallback_contents,
    index_keys,
    search_token,
    upsert_contents,
)
from app.features.skill_gap.gap import LearningGap
from app.models.learning import LearningContent


def _course(cid, title, **kw):
    url = f"https://www.kmooc.kr/view/course/detail/{cid}"
    return KmoocCourse(external_id=cid, title=title, url=url, **kw)


def _gap(key, label, importance="required"):
    return LearningGap(key=key, label=label, importance=importance, evidence_fields=())


# --------------------------------------------------------------------------
# 순수
# --------------------------------------------------------------------------

def test_index_keys_uses_a11_vocab():
    text = {"title": "SQL과 파이썬으로 하는 데이터 분석", "summary": "Docker 실습", "classfy": None}
    keys = index_keys(text)
    assert {"sql", "python", "docker"} <= set(keys)


def test_index_keys_ignores_non_vocab_words():
    assert index_keys({"title": "행복한 삶의 인문학", "summary": None, "classfy": "인문"}) == []


@pytest.mark.parametrize(
    ("label", "token"),
    [
        ("IFRS17", "IFRS17"),
        ("K-ICS 계리결산에 대한 실무적 이해", "K-ICS"),
        ("계리소프트웨어", "계리소프트웨어"),
        ("관련 업무 경험", None),
    ],
)
def test_search_token(label, token):
    assert search_token(label) == token


def test_like_escape_wildcards():
    assert _like_escape("a_b%c") == "a\\_b\\%c"


def test_work24_keywords_use_vocab_keys():
    from app.features.matching.vocab import TERMS
    from app.features.roadmap.work24 import KEYWORDS

    vocab = {t.key for t in TERMS}
    assert vocab <= set(KEYWORDS)  # 사전 전 항목
    assert set(KEYWORDS) - vocab == {"security", "network"}  # 사전 밖은 추가 2개뿐
    assert KEYWORDS["sql"] == "SQL" and KEYWORDS["python"] == "파이썬"  # 발음 표기 아님


# --------------------------------------------------------------------------
# DB — 색인 적재·대체 검색·로드맵
# --------------------------------------------------------------------------

def _rows(session, source="kmooc"):
    return {r.external_id: r for r in session.execute(
        select(LearningContent).where(LearningContent.source == source)
    ).scalars()}


def test_upsert_indexes_new_and_keeps_existing_keys(db_session):
    upsert_contents(db_session, [_course("k1", "SQL 기초")])
    db_session.flush()
    row = _rows(db_session)["k1"]
    assert "sql" in row.competency_keys

    row.competency_keys = [*row.competency_keys, "manual"]  # 이전 태깅
    db_session.flush()
    upsert_contents(db_session, [_course("k1", "SQL 기초와 Python")])
    db_session.flush()
    assert {"sql", "python", "manual"} <= set(row.competency_keys)  # 합집합, 안 지움


def test_fallback_finds_title_for_unlinked_domain_gap(db_session):
    upsert_contents(db_session, [_course("k2", "IFRS17 보험회계 실무"), _course("k3", "일반 회계원리")])
    db_session.flush()
    refs = fallback_contents(db_session, [_gap("ifrs17", "IFRS17")])
    assert [r.title for r in refs] == ["IFRS17 보험회계 실무"]
    assert "ifrs17" in refs[0].competency_keys  # 메모리상 갭 키 부착
    assert "ifrs17" not in (_rows(db_session)["k2"].competency_keys or [])  # DB 키는 안 바뀜


def test_fallback_escapes_like_wildcards(db_session):
    upsert_contents(db_session, [_course("k4", "AxB 개론")])
    db_session.flush()
    assert fallback_contents(db_session, [_gap("a_b", "A_B")]) == []  # _가 한 글자 와일드카드로 안 먹힘


def test_build_roadmap_links_domain_gap_via_fallback(db_session):
    upsert_contents(db_session, [_course("k5", "K-ICS 지급여력제도 이해", est_hours=3.0)])
    db_session.flush()
    plan = build_roadmap(db_session, [_gap("k-ics계리결산", "K-ICS 계리결산에 대한 실무적 이해")])
    assert plan.selections[0].primary is not None
    assert plan.selections[0].primary.title == "K-ICS 지급여력제도 이해"
    assert plan.uncovered == []


# --------------------------------------------------------------------------
# K-MOOC 배치 — 새 강좌만 상세, 상한, 기존 강좌는 키만 보강
# --------------------------------------------------------------------------

def test_kmooc_batch_details_only_new_with_cap(db_session, monkeypatch):
    from app.batch.jobs_collector import collect_kmooc

    upsert_contents(db_session, [_course("old", "행복학", est_hours=5.0, summary="Python 실습 포함")])
    db_session.flush()
    _rows(db_session)["old"].competency_keys = []  # 색인 도입 전에 저장된 행처럼
    db_session.flush()
    listed = [_course("old", "행복학"), _course("n1", "SQL 입문"), _course("n2", "Docker 입문")]
    detail_calls = []

    monkeypatch.setattr(kmooc, "collect", lambda fetch_list, fetch_detail=None, **kw: listed)

    def fake_detail(cid):
        detail_calls.append(cid)
        return {"resultCode": "00", "results": {"vod_playtime": 7200, "summary": "<p>요약</p>"}}

    monkeypatch.setattr(kmooc, "fetch_course_detail", fake_detail)
    out = collect_kmooc(db_session, detail_cap=1)
    db_session.flush()

    rows = _rows(db_session)
    assert detail_calls == ["n1"]  # 새 강좌만, 상한 1
    assert out["pending_detail"] == 1 and "n2" not in rows  # 다음 실행으로
    assert rows["n1"].est_hours == 2.0 and "sql" in rows["n1"].competency_keys
    assert rows["old"].est_hours == 5.0  # 기존 강좌는 덮어쓰지 않음(시간 유지)
    assert "python" in rows["old"].competency_keys and out["reindexed"] == 1  # 요약으로 키 보강
