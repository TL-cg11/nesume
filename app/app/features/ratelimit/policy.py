"""C7 — 레이트리밋 한도·시간창 (조정 가능, 하드코딩 금지).

spec §9(차단 정책)·§418(탈취 세션 제한). 값은 **env로 조정**한다 — 공용 `config.py`를 안 건드리고
배포에서 환경변수로만 바꾸게 둔다(C4·C14 키와 같은 결). D 차단정책 문서(§9)와 수치를 맞춘다.

두 축 모두 "키별 시간창 안의 카운트가 한도 이상이면 거부"라는 **같은 모양**이라 `Limit` 하나로 표현한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    """env 정수 조정값. 파싱 불가·0 이하는 기본값(설정 실수로 한도가 풀리지 않게)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class Limit:
    """한 축의 한도. `window_seconds` 창 안에서 `max_count` 이상이면 거부한다."""

    name: str
    max_count: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimits:
    """C7이 집행하는 한도 묶음."""

    #: 비용 쿼터 — 사용자별 요청/분(남용 방지), LLM 토큰/일(비용). (§13 561)
    requests_per_min: Limit
    tokens_per_day: Limit
    #: 탈취 세션 제한 — 탈취 판정 N회/창 넘으면 그 세션 LLM 차단. (§418 기본 5회·10분)
    exfil_per_session: Limit


def load_limits() -> RateLimits:
    """env에서 한도를 읽어 묶는다(미설정 시 기본값). 배포는 환경변수로만 조정."""
    return RateLimits(
        requests_per_min=Limit(
            "requests_per_min", _int_env("RL_REQUESTS_PER_MIN", 60), 60
        ),
        tokens_per_day=Limit(
            "tokens_per_day", _int_env("RL_TOKENS_PER_DAY", 100_000), 86_400
        ),
        exfil_per_session=Limit(
            "exfil_per_session",
            _int_env("RL_EXFIL_VIOLATIONS", 5),
            _int_env("RL_EXFIL_BLOCK_SECONDS", 600),
        ),
    )
