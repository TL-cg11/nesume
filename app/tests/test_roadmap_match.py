"""C14 매칭 순수 로직 테스트 (DB 없음)."""
import uuid

from app.features.roadmap.match import (
    ContentRef,
    select_for_gaps,
    to_learning_items,
)
from app.features.skill_gap.gap import LearningGap


def _gap(key, label="L", importance="required"):
    return LearningGap(key=key, label=label, importance=importance, evidence_fields=())


def _content(keys, *, title="C", mode="online", est=0.0, rating=None, cert=None):
    return ContentRef(
        content_id=uuid.uuid4(),
        source="kmooc",
        title=title,
        url="https://kmooc.kr/x",
        mode=mode,
        competency_keys=tuple(keys),
        est_hours=est,
        rating=rating,
        certificate=cert,
    )


def test_match_by_key_intersection():
    gaps = [_gap("aws"), _gap("docker")]
    contents = [_content(["aws"], title="A"), _content(["k8s"], title="B")]
    sel = select_for_gaps(gaps, contents)
    assert sel[0].primary.title == "A"       # aws 매칭
    assert sel[1].primary is None            # docker 매칭 없음


def test_rank_prefers_certificate_then_rating():
    gaps = [_gap("aws")]
    contents = [
        _content(["aws"], title="no-cert-high", rating=4.9, cert=False),
        _content(["aws"], title="cert-low", rating=3.0, cert=True),
    ]
    sel = select_for_gaps(gaps, contents)
    assert sel[0].primary.title == "cert-low"   # 수료증이 평점보다 우선


def test_rank_shorter_course_first_when_tied():
    gaps = [_gap("aws")]
    contents = [
        _content(["aws"], title="long", est=20.0),
        _content(["aws"], title="short", est=5.0),
    ]
    sel = select_for_gaps(gaps, contents)
    assert sel[0].primary.title == "short"


def test_mode_filter_excludes_other_mode():
    gaps = [_gap("aws")]
    contents = [_content(["aws"], title="on", mode="online"), _content(["aws"], title="off", mode="offline")]
    sel = select_for_gaps(gaps, contents, mode="offline")
    assert sel[0].primary.title == "off"
    assert len(sel[0].contents) == 1


def test_per_gap_limit():
    gaps = [_gap("aws")]
    contents = [_content(["aws"], title=f"c{i}", est=float(i + 1)) for i in range(5)]
    sel = select_for_gaps(gaps, contents, per_gap=2)
    assert len(sel[0].contents) == 2


def test_to_learning_items_keeps_gap_order_and_uses_primary():
    gaps = [_gap("aws", label="AWS"), _gap("docker", label="Docker")]
    contents = [_content(["aws"], title="AWS강좌", est=10.0)]
    items = to_learning_items(select_for_gaps(gaps, contents))
    assert [i.key for i in items] == ["aws", "docker"]   # 순서 유지
    assert items[0].est_hours == 10.0 and items[0].title == "AWS강좌"
    assert items[1].est_hours == 0.0 and items[1].title == ""  # 콘텐츠 없는 갭도 역량으로 포함


# --- 평점 정규화·회차 중복·"전체" 모드 섞기 (docs/C14.md "전체" 선택 시 오프라인만 뜨는 문제) ---

def _ref(title, *, mode="online", source="kmooc", rating=None, group=None, keys=("sql",)):
    return ContentRef(
        content_id=uuid.uuid4(), source=source, title=title, url="https://x", mode=mode,
        competency_keys=tuple(keys), rating=rating, group=group,
    )


def test_rating_normalized_by_source_scale():
    """고용24 80/100(0.8) < K-MOOC 4.5/5(0.9) — 원점수로 비교하면 반대가 된다."""
    contents = [_ref("w", source="work24", rating=80.0), _ref("k", source="kmooc", rating=4.5)]
    assert select_for_gaps([_gap("sql")], contents, mode="online")[0].primary.title == "k"


def test_same_course_sessions_deduped():
    contents = [
        _ref("회차1", source="work24", rating=90.0, group="work24:P1:I1"),
        _ref("회차2", source="work24", rating=80.0, group="work24:P1:I1"),
        _ref("다른과정", source="work24", rating=70.0, group="work24:P2:I1"),
    ]
    sel = select_for_gaps([_gap("sql")], contents, mode="online")
    assert [c.title for c in sel[0].contents] == ["회차1", "다른과정"]


def test_all_mode_alternates_primary_and_mixes_alternates():
    """전체: 두 모드가 다 있는 갭마다 1순위가 온라인 → 오프라인 번갈아, 대안에 다른 모드 포함."""
    contents = [
        _ref("off-hi", mode="offline", rating=5.0, keys=("sql", "python")),
        _ref("off-mid", mode="offline", rating=4.0, keys=("sql", "python")),
        _ref("on-lo", mode="online", rating=1.0, keys=("sql", "python")),
    ]
    sel = select_for_gaps([_gap("sql"), _gap("python")], contents)
    assert [c.title for c in sel[0].contents] == ["on-lo", "off-hi", "off-mid"]
    assert [c.title for c in sel[1].contents] == ["off-hi", "on-lo", "off-mid"]


def test_all_mode_single_mode_gap_does_not_use_turn():
    contents = [
        _ref("off-only", mode="offline", keys=("docker",)),
        _ref("on", mode="online", keys=("sql",)),
        _ref("off", mode="offline", keys=("sql",)),
    ]
    sel = select_for_gaps([_gap("docker"), _gap("sql")], contents)
    assert sel[0].primary.title == "off-only"   # 한 모드뿐 → 차례 안 씀
    assert sel[1].primary.title == "on"         # 첫 차례는 여전히 온라인
