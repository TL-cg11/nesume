"""C8 추천 재정렬·집계 테스트. DB·A11·모델 불필요(순수)."""
import uuid

from app.features.recommend.rerank import (
    KEYWORD_WEIGHT,
    VECTOR_WEIGHT,
    Candidate,
    KeywordMatch,
    aggregate_candidates,
    keyword_match_rate,
    rerank,
    similarity_from_distance,
)


def _pid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


def test_similarity_clamps_negative_to_zero():
    assert similarity_from_distance(0.0) == 1.0
    assert similarity_from_distance(1.0) == 0.0
    assert similarity_from_distance(1.8) == 0.0  # 무관(음수 유사도) → 0


def test_aggregate_keeps_best_per_posting():
    # 같은 공고(1)가 여러 청크·쿼리로 중복 → 최고 유사도(거리 최소)만
    rows = [(_pid(1), 0.4), (_pid(1), 0.1), (_pid(2), 0.5)]
    cands = {c.posting_id: c.vector_score for c in aggregate_candidates(rows)}
    assert cands[_pid(1)] == similarity_from_distance(0.1)  # 0.9 (더 가까운 쪽)
    assert len(cands) == 2


def test_keyword_match_rate_ratio_and_matched():
    km = keyword_match_rate(["python", "aws", "docker"], held_keys={"python", "docker", "sql"})
    assert km.rate == 2 / 3
    assert set(km.matched) == {"python", "docker"}


def test_keyword_rate_zero_when_no_required():
    assert keyword_match_rate([], held_keys={"python"}).rate == 0.0
    assert keyword_match_rate([], held_keys={"python"}).available is False  # 비교 불가
    assert keyword_match_rate(["aws"], held_keys=set()).available is True   # 비교했는데 0


def test_keyword_required_deduped():
    km = keyword_match_rate(["python", "python", "aws"], held_keys={"python"})
    assert km.rate == 1 / 2  # 중복 요구 키는 한 번


def test_rerank_blends_5_5_and_sorts():
    cands = [Candidate(_pid(1), 0.9), Candidate(_pid(2), 0.5)]
    kw = {
        _pid(1): KeywordMatch(0.0, ()),      # 벡터 높지만 키워드 0
        _pid(2): KeywordMatch(1.0, ("a",)),  # 벡터 중간이지만 키워드 만점
    }
    recs = rerank(cands, kw)
    # 1: 0.5*0.9 + 0.5*0.0 = 0.45 / 2: 0.5*0.5 + 0.5*1.0 = 0.75 → 2가 먼저
    assert [r.posting_id for r in recs] == [_pid(2), _pid(1)]
    assert abs(recs[0].final_score - 0.75) < 1e-9
    assert recs[0].matched_keywords == ("a",)


def test_rerank_top_k_truncates():
    cands = [Candidate(_pid(i), 1.0 - i / 100) for i in range(30)]
    recs = rerank(cands, {}, top_k=20)
    assert len(recs) == 20
    assert recs[0].posting_id == _pid(0)  # 최고 벡터 점수


def test_rerank_missing_keyword_defaults_zero():
    recs = rerank([Candidate(_pid(1), 0.8)], {})  # 키워드 정보 없음
    assert recs[0].keyword_score == 0.0
    assert abs(recs[0].final_score - VECTOR_WEIGHT * 0.8) < 1e-9
    assert recs[0].keyword_available is False  # 점수는 그대로, 화면은 "키워드 정보 없음"


def test_rerank_carries_keyword_available():
    cands = [Candidate(_pid(1), 0.9), Candidate(_pid(2), 0.5)]
    kw = {_pid(1): keyword_match_rate([], set()), _pid(2): keyword_match_rate(["aws"], set())}
    by_id = {r.posting_id: r for r in rerank(cands, kw)}
    assert by_id[_pid(1)].keyword_available is False  # 공고에 비교할 기술 없음
    assert by_id[_pid(2)].keyword_available is True   # 비교했는데 0%


def test_weights_sum_to_one():
    assert VECTOR_WEIGHT + KEYWORD_WEIGHT == 1.0
