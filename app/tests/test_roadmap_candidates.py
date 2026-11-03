"""C14 "전체"면 온라인·오프라인 둘 다 · 강좌 전체 보기·추가·교체 · 의미 검색 (docs/C14.md 2026-10-29).

순수(picks·배치 칸)와 DB(conftest `db_session`) 혼합. 임베더는 가짜(고정 벡터)로 의미 검색 경로만 확인한다.
"""
import uuid

import pytest
from sqlalchemy import select

from app.features.roadmap import service
from app.features.roadmap.match import ContentRef, GapContent, picks, to_learning_items
from app.features.skill_gap.gap import LearningGap
from app.models.embedding import EMBED_DIM, LearningContentEmbedding
from app.models.learning import LearningContent
from app.models.user import User
from app.retrieval.reindex import content_text, reindex_contents


def _gap(key, label=None):
    return LearningGap(key=key, label=label or key, importance="required", evidence_fields=())


def _ref(mode, title="t"):
    return ContentRef(content_id=uuid.uuid4(), source="kmooc", title=title, url="https://x", mode=mode,
                      competency_keys=("k",))


def _unit(i):
    v = [0.0] * EMBED_DIM
    v[i] = 1.0
    return v


class _Embedder:
    """라벨 → 고정 벡터. 매핑에 없는 라벨은 축 0과 직교하는 축 9."""

    def __init__(self, by_label=None):
        self.by_label = by_label or {}
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [self.by_label.get(t, _unit(9)) for t in texts]


def _user(session) -> str:
    uid = f"u-{uuid.uuid4()}"
    session.add(User(id=uid))
    session.flush()
    return uid


def _content(session, title, *, mode="online", keys=(), source="kmooc", rating=None, active=True):
    c = LearningContent(source=source, external_id=uuid.uuid4().hex, mode=mode, title=title,
                        url="https://www.kmooc.kr/x", competency_keys=list(keys), rating=rating,
                        is_active=active)
    session.add(c)
    session.flush()
    return c


def _roadmap(session, owner, gaps, mode=None, embedder=None):
    plan = service.build_roadmap(session, gaps, mode=mode, embedder=embedder)
    rm = service.save_roadmap(session, owner_id=owner, job_posting_id=None, weekly_hours=5, plan=plan)
    session.flush()
    return rm, [i for i, _ in service.get_items(session, roadmap_id=rm.id, owner_id=owner)]


# --------------------------------------------------------------------------
# 순수 — "전체"면 두 방법
# --------------------------------------------------------------------------

def test_picks_both_modes_takes_one_of_each():
    on, off, on2 = _ref("online"), _ref("offline"), _ref("online")
    sel = GapContent(gap=_gap("k"), contents=(on, on2, off))
    assert picks(sel) == (on,)
    assert picks(sel, both_modes=True) == (on, off)


def test_picks_single_mode_only_one():
    on, on2 = _ref("online"), _ref("online")
    assert picks(GapContent(gap=_gap("k"), contents=(on, on2)), both_modes=True) == (on,)


def test_learning_items_slots_per_gap():
    sel = GapContent(gap=_gap("k"), contents=(_ref("online"), _ref("offline")))
    items = to_learning_items([sel, GapContent(gap=_gap("z"), contents=())], both_modes=True)
    assert [(i.key, i.slot) for i in items] == [("k", 0), ("k", 1), ("z", 0)]


# --------------------------------------------------------------------------
# DB — 저장(두 방법·역량 정보), 의미 검색
# --------------------------------------------------------------------------

def test_all_mode_saves_online_and_offline_with_gap_info(db_session):
    owner = _user(db_session)
    _content(db_session, "SQL 온라인", mode="online", keys=["sqlx"])
    _content(db_session, "SQL 오프라인", mode="offline", keys=["sqlx"], source="work24")
    _, items = _roadmap(db_session, owner, [_gap("sqlx", "SQL")])
    modes = sorted(db_session.get(LearningContent, i.content_id).mode for i in items)
    assert modes == ["offline", "online"]
    assert {(i.gap_key, i.gap_label, i.match_kind) for i in items} == {("sqlx", "SQL", "key")}


def test_selected_mode_saves_one(db_session):
    owner = _user(db_session)
    _content(db_session, "SQL 온라인2", mode="online", keys=["sqly"])
    _content(db_session, "SQL 오프라인2", mode="offline", keys=["sqly"], source="work24")
    _, items = _roadmap(db_session, owner, [_gap("sqly", "SQL")], mode="offline")
    assert len(items) == 1 and db_session.get(LearningContent, items[0].content_id).mode == "offline"


def test_semantic_fallback_above_threshold_only(db_session):
    owner = _user(db_session)
    near = _content(db_session, "철도 인프라 BIM")
    far = _content(db_session, "조선의 역사")
    db_session.add_all([
        LearningContentEmbedding(content_id=near.id, content="x", embedding=_unit(0)),
        LearningContentEmbedding(content_id=far.id, content="y", embedding=_unit(1)),
    ])
    db_session.flush()
    _, items = _roadmap(db_session, owner, [_gap("토목xyz", "토목xyz")],
                        embedder=_Embedder({"토목xyz": _unit(0)}))
    assert [(i.content_id, i.match_kind) for i in items] == [(near.id, "semantic")]


def test_no_embedder_keeps_gap_without_course(db_session):
    owner = _user(db_session)
    _, items = _roadmap(db_session, owner, [_gap("없는역량q", "없는역량q")])
    assert len(items) == 1 and items[0].content_id is None and items[0].title == "없는역량q"


# --------------------------------------------------------------------------
# DB — 전체 보기·추가·교체
# --------------------------------------------------------------------------

def test_candidates_all_paged_sorted_and_mode_filter(db_session):
    owner = _user(db_session)
    for n in range(5):
        _content(db_session, f"Rust 강좌 {n}", keys=["rustz"], rating=float(n))
    _content(db_session, "Rust 오프라인", mode="offline", keys=["rustz"], source="work24")
    rm, items = _roadmap(db_session, owner, [_gap("rustz", "Rust")], mode="online")

    total, page1, in_rm = service.item_candidates(
        db_session, roadmap_id=rm.id, item_id=items[0].id, owner_id=owner, page=1, size=4)
    assert total == 6 and len(page1) == 4
    assert page1[0].title == "Rust 강좌 4"  # 평점순
    assert items[0].content_id in in_rm
    total2, page2, _ = service.item_candidates(
        db_session, roadmap_id=rm.id, item_id=items[0].id, owner_id=owner, page=2, size=4)
    assert len(page2) == 2
    t_off, off, _ = service.item_candidates(
        db_session, roadmap_id=rm.id, item_id=items[0].id, owner_id=owner, mode="offline")
    assert t_off == 1 and off[0].title == "Rust 오프라인"


def test_candidates_other_owner_not_found(db_session):
    owner, other = _user(db_session), _user(db_session)
    _content(db_session, "Go 강좌", keys=["goz"])
    rm, items = _roadmap(db_session, owner, [_gap("goz", "Go")])
    with pytest.raises(service.RoadmapNotFound):
        service.item_candidates(db_session, roadmap_id=rm.id, item_id=items[0].id, owner_id=other)


def test_user_item_has_no_gap_info(db_session):
    owner = _user(db_session)
    rm, _ = _roadmap(db_session, owner, [_gap("goy", "Go")])
    mine = service.add_user_item(db_session, roadmap_id=rm.id, owner_id=owner, title="내 강좌")
    db_session.flush()
    with pytest.raises(service.NoGapInfo):
        service.item_candidates(db_session, roadmap_id=rm.id, item_id=mine.id, owner_id=owner)


def test_add_and_replace_candidate(db_session):
    owner = _user(db_session)
    a = _content(db_session, "Kotlin A", keys=["ktz"], rating=5.0)
    b = _content(db_session, "Kotlin B", keys=["ktz"], rating=1.0)
    rm, items = _roadmap(db_session, owner, [_gap("ktz", "Kotlin")], mode="online")
    base = items[0]
    assert base.content_id == a.id

    ids = {"roadmap_id": rm.id, "item_id": base.id, "owner_id": owner, "content_id": b.id}
    added = service.add_candidate(db_session, **ids)
    db_session.flush()
    assert (added.gap_key, added.week, added.match_kind) == ("ktz", base.week, "key")

    service.replace_with_candidate(db_session, **ids)
    assert base.content_id == b.id and base.gap_key == "ktz"


def test_pick_inactive_content_rejected(db_session):
    owner = _user(db_session)
    _content(db_session, "Scala A", keys=["scz"])
    gone = _content(db_session, "Scala old", keys=["scz"], active=False)
    rm, items = _roadmap(db_session, owner, [_gap("scz", "Scala")], mode="online")
    with pytest.raises(service.ContentUnavailable):
        service.replace_with_candidate(db_session, roadmap_id=rm.id, item_id=items[0].id, owner_id=owner,
                                       content_id=gone.id)


# --------------------------------------------------------------------------
# 강좌 임베딩 배치
# --------------------------------------------------------------------------

def test_reindex_contents_new_unchanged_and_cap(db_session):
    a = _content(db_session, "임베딩 A")
    a.summary = "요약 " * 200
    _content(db_session, "임베딩 B", source="work24", mode="offline").summary = "기관 · 서울 · 2026"
    db_session.flush()
    assert content_text(a).startswith("임베딩 A — 요약") and len(content_text(a)) < 320

    emb = _Embedder()
    first = reindex_contents(db_session, emb, cap=1)
    assert first["embedded"] == 1 and first["pending"] >= 1
    reindex_contents(db_session, emb)
    db_session.flush()
    again = reindex_contents(db_session, _Embedder())
    assert again["embedded"] == 0
    row = db_session.execute(
        select(LearningContentEmbedding).join(LearningContent).where(LearningContent.title == "임베딩 B")
    ).scalar_one()
    assert row.content == "임베딩 B"  # 고용24 요약(기관·지역·기간)은 넣지 않는다


def _save(session, owner, gaps, mode=None):
    plan = service.build_roadmap(session, gaps, mode=mode)
    rm = service.save_roadmap(
        session, owner_id=owner, job_posting_id=None, weekly_hours=5, plan=plan, mode=mode
    )
    session.flush()
    return rm


def test_new_roadmap_replaces_draft_but_keeps_saved(db_session):
    owner, other = _user(db_session), _user(db_session)
    _content(db_session, "Swift 온라인", keys=["swz"])
    gaps = [_gap("swz", "Swift")]

    first = _save(db_session, owner, gaps)
    service.update_roadmap(db_session, roadmap_id=first.id, owner_id=owner, save=True, name="  내 iOS  ")
    db_session.flush()
    others_draft = _save(db_session, other, gaps)
    draft1 = _save(db_session, owner, gaps, mode="online")
    draft2 = _save(db_session, owner, gaps)  # 이전 초안(draft1)은 지워진다
    db_session.expire_all()

    mine = {r.id: r for r in service.list_roadmaps(db_session, owner_id=owner)}
    assert set(mine) == {first.id, draft2.id} and draft1.id not in mine
    assert mine[first.id].saved_at is not None and mine[first.id].name == "내 iOS"
    assert mine[draft2.id].saved_at is None
    theirs = [r.id for r in service.list_roadmaps(db_session, owner_id=other)]
    assert theirs == [others_draft.id]  # 남의 초안은 그대로


def test_save_twice_keeps_first_time_and_blank_name_clears(db_session):
    owner = _user(db_session)
    _content(db_session, "Dart 온라인", keys=["dartz"])
    rm = _save(db_session, owner, [_gap("dartz", "Dart")])
    service.update_roadmap(db_session, roadmap_id=rm.id, owner_id=owner, save=True, name="a")
    db_session.flush()
    db_session.refresh(rm)
    first_time = rm.saved_at
    service.update_roadmap(db_session, roadmap_id=rm.id, owner_id=owner, save=True, name="  ")
    db_session.flush()
    db_session.refresh(rm)
    assert rm.saved_at == first_time and rm.name is None


def test_update_other_owner_not_found(db_session):
    owner, other = _user(db_session), _user(db_session)
    rm = _save(db_session, owner, [_gap("nz", "N")])
    with pytest.raises(service.RoadmapNotFound):
        service.update_roadmap(db_session, roadmap_id=rm.id, owner_id=other, save=True)


def test_draft_unique_per_owner_in_db(db_session):
    from sqlalchemy.exc import IntegrityError

    from app.models.learning import LearningRoadmap

    owner = _user(db_session)
    db_session.add(LearningRoadmap(owner_id=owner))
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(LearningRoadmap(owner_id=owner))
        db_session.flush()


def test_save_limit_needs_confirm_then_drops_oldest(db_session):
    from datetime import UTC, datetime, timedelta

    from app.models.learning import LearningRoadmap

    owner, other = _user(db_session), _user(db_session)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    saved = [
        LearningRoadmap(owner_id=owner, saved_at=base + timedelta(days=i))
        for i in range(service.MAX_SAVED_ROADMAPS)
    ]
    db_session.add_all(saved + [LearningRoadmap(owner_id=other, saved_at=base)])
    db_session.flush()
    draft = _save(db_session, owner, [_gap("limz", "L")])

    with pytest.raises(service.SavedLimitReached):
        service.update_roadmap(db_session, roadmap_id=draft.id, owner_id=owner, save=True)
    service.update_roadmap(db_session, roadmap_id=draft.id, owner_id=owner, save=True, replace_oldest=True)
    db_session.flush()
    db_session.expire_all()

    mine = {r.id for r in service.list_roadmaps(db_session, owner_id=owner)}
    assert len(mine) == service.MAX_SAVED_ROADMAPS
    assert saved[0].id not in mine and draft.id in mine and saved[1].id in mine
    assert len(service.list_roadmaps(db_session, owner_id=other)) == 1  # 남의 저장본은 그대로


def test_save_under_limit_needs_no_confirm(db_session):
    owner = _user(db_session)
    rm = _save(db_session, owner, [_gap("ulz", "U")])
    service.update_roadmap(db_session, roadmap_id=rm.id, owner_id=owner, save=True)
    db_session.flush()
    db_session.refresh(rm)
    assert rm.saved_at is not None
