"""C8 — 추천 API 스키마.

저장하지 않는다. 사용자 보유 역량(`held_keys`)과 필터를 받아 맞춤 공고를 돌려줄 뿐이다.

`held_keys`를 **요청으로 받는다** — 보유 역량은 B의 경험·스킬 데이터라, C가 직접 읽으면 단일 조회
경로 합의가 깨진다(A11 `analyze`가 경험을 요청으로 받는 것과 같은 이유, docs/C8.md). 조립은 호출측.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

#: 한 번에 받는 보유 역량·필터 코드 상한(과도한 입력·정규식 시간 방지).
MAX_HELD_KEYS = 200
MAX_FILTER_CODES = 40

#: 반환 개수 상한(기본 20, docs/C8.md 결정).
MAX_TOP_K = 50


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: 사용자 보유 역량 정규화 키(경험·스킬·자소서). 비면 키워드 신호 없이 벡터만으로 추천.
    held_keys: list[str] = Field(default_factory=list, max_length=MAX_HELD_KEYS)
    #: 지역(region_code)·직무(job_code) 필터. 비면 전체(필터 off).
    region_codes: list[str] = Field(default_factory=list, max_length=MAX_FILTER_CODES)
    job_codes: list[str] = Field(default_factory=list, max_length=MAX_FILTER_CODES)
    top_k: int = Field(default=20, ge=1, le=MAX_TOP_K)


class PostingBrief(BaseModel):
    """추천 공고 요약(제목·직무). 공고 글은 C 창구 `get_posting_fields`로만 읽는다."""

    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    job_name: str | None = None
    #: 출처(seoul / work24_open …) — 화면 출처 문구용(서울시는 "서울특별시 공공데이터" 표시 의무).
    source: str | None = None
    #: 원문 링크(공채속보만, 기업별 외부 도메인·http/https만 저장). 서울시는 None → 화면은 접수방법 안내.
    url: str | None = None


class RecommendationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    posting_id: uuid.UUID
    #: 최종 점수 = 0.5 벡터 + 0.5 키워드율(docs/C8.md 결정2).
    score: float
    vector_score: float
    keyword_score: float
    #: 왜 추천됐는지 — 사용자 보유 ∩ 공고 요구 역량.
    matched_keywords: list[str]
    posting: PostingBrief | None = None


class RecommendResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RecommendationOut]
    #: 개인 벡터가 없어 콜드스타트인가. true면 items는 비고 안내를 띄운다.
    cold_start: bool
    #: 콜드스타트일 때 화면에 함께 보여줄 안내.
    notice: str | None = None
