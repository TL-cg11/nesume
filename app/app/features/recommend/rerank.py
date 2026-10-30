"""C8 — 추천 재정렬·집계 (순수 로직, DB·A11·모델 무관).

C6 `search_public`가 준 벡터 검색 결과 위에 **공고 단위 집계 + 벡터·키워드 하이브리드 재정렬**을
얹는다. 흐름(docs/C8.md): 멀티벡터 검색 → 공고 id로 집계(최고 유사도) → 0.5 벡터 + 0.5 키워드 →
상위 N. 이 모듈은 **값만 받아 계산**하므로 DB·임베딩·A11 없이 단위 테스트된다(배선은 service.py).

키워드 매칭률의 "보유 역량"은 **자소서에 쓴 것만이 아니라 경험·스킬 포함 사용자가 가진 키 전체**다
(추천은 "쓴 내용"이 아니라 "맞는지"가 기준, 2026-10-22 결정). A11 covered∪in_experience_only에 해당.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

#: 재정렬 가중치 — 벡터(recall) : 키워드(정밀) = 5:5 (docs/C8.md 결정2, 통합 후 A/B 조정).
VECTOR_WEIGHT = 0.5
KEYWORD_WEIGHT = 0.5

#: 최종 반환 개수.
DEFAULT_TOP_K = 20

#: 재정렬 전 후보 수(멀티벡터 병합·청크 dedup 여유, docs/C8.md 결정3).
DEFAULT_CANDIDATES = 60


@dataclass(frozen=True)
class Candidate:
    """집계된 공고 후보 1건 — 공고 id + 벡터 유사도(0~1, 높을수록 유사)."""

    posting_id: uuid.UUID
    vector_score: float


@dataclass(frozen=True)
class KeywordMatch:
    """공고별 키워드 매칭 결과 — 매칭률(0~1)과 맞은 역량 키(설명용)."""

    rate: float
    matched: tuple[str, ...] = ()
    #: 공고에서 비교할 사전 기술이 하나라도 나왔나. False면 rate 0은 "안 맞음"이 아니라 "비교 불가"
    available: bool = True


@dataclass(frozen=True)
class Recommendation:
    """추천 결과 1건. `matched_keywords`로 '왜 추천됐는지' 설명가능성 확보."""

    posting_id: uuid.UUID
    vector_score: float
    keyword_score: float
    final_score: float
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)
    #: False = 공고에 비교할 사전 기술이 없어 키워드율이 의미 없음(화면은 "키워드 정보 없음")
    keyword_available: bool = True


def similarity_from_distance(distance: float) -> float:
    """코사인 거리(pgvector `cosine_distance`)를 유사도 점수로. 음수(무관)는 0으로 자른다.

    bge-m3는 정규화 임베딩 → distance = 1 − cos. 1 − distance를 [0,1]로 클램프한 **상대 점수**다
    (절대 품질 지표 아님 — 재정렬 순위용). 키워드율[0,1]과 같은 눈금으로 맞춘다.
    """
    return max(0.0, min(1.0, 1.0 - distance))


def aggregate_candidates(rows: Iterable[tuple[uuid.UUID, float]]) -> list[Candidate]:
    """멀티벡터 검색 결과(여러 쿼리 × 여러 청크)를 **공고 id로 묶어 최고 유사도**만 남긴다.

    `rows` = (source_id=공고 id, distance) 들. 같은 공고가 여러 청크·여러 쿼리로 나와도 **한 번**,
    가장 가까운(최고 유사도) 점수를 공고 점수로 삼는다(docs/C8.md 공고 단위 집계).
    """
    best: dict[uuid.UUID, float] = {}
    for source_id, distance in rows:
        sim = similarity_from_distance(distance)
        if source_id not in best or sim > best[source_id]:
            best[source_id] = sim
    return [Candidate(pid, sim) for pid, sim in best.items()]


def keyword_match_rate(
    required_keys: Iterable[str], held_keys: Iterable[str]
) -> KeywordMatch:
    """공고 요구 역량 중 사용자가 **보유한 비율**. 요구 역량이 없으면 0(키워드 신호 없음).

    `required_keys`=공고 요구 역량(A11 추출), `held_keys`=사용자 보유 역량(경험·스킬·자소서).
    정규화 키 정확 일치로 센다(동의어는 A11·임베딩이 담당). 중복 요구 키는 한 번만.
    """
    required = list(dict.fromkeys(required_keys))
    if not required:
        return KeywordMatch(0.0, (), available=False)
    held = set(held_keys)
    matched = tuple(k for k in required if k in held)
    return KeywordMatch(len(matched) / len(required), matched)


def rerank(
    candidates: Iterable[Candidate],
    keyword_by_posting: Mapping[uuid.UUID, KeywordMatch],
    *,
    vector_weight: float = VECTOR_WEIGHT,
    keyword_weight: float = KEYWORD_WEIGHT,
    top_k: int = DEFAULT_TOP_K,
) -> list[Recommendation]:
    """하이브리드 재정렬 → 상위 top_k. `최종 = w_v·벡터 + w_k·키워드율`.

    공고에 비교할 기술 키워드가 없으면(`available=False`) **벡터 점수만으로** 최종 점수를 낸다
    (사용자 결정 2026-10-30 — 키워드 0으로 계산하면 비교 불가 공고가 반점수로 밀렸다, docs/C8.md).
    동점이면 벡터 점수가 높은 쪽 먼저.
    """
    recs: list[Recommendation] = []
    for c in candidates:
        km = keyword_by_posting.get(c.posting_id, KeywordMatch(0.0, (), available=False))
        if km.available:
            final = vector_weight * c.vector_score + keyword_weight * km.rate
        else:
            final = c.vector_score  # 키워드 정보 없음 → 벡터만
        recs.append(
            Recommendation(
                posting_id=c.posting_id,
                vector_score=c.vector_score,
                keyword_score=km.rate,
                final_score=final,
                matched_keywords=km.matched,
                keyword_available=km.available,
            )
        )
    recs.sort(key=lambda r: (r.final_score, r.vector_score), reverse=True)
    return recs[:top_k]
