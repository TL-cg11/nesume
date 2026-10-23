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
