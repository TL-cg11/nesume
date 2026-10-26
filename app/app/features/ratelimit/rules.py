"""C7 — 창 카운터 판정 (순수 로직, DB·시간 I/O 무관).

두 축(비용 쿼터·탈취 세션 제한)이 같은 모양이라 판정도 하나로 합친다:
**시간창 안의 누적 count가 한도(max_count) 이상이면 거부**하고, 창이 리셋될 때까지 `retry_after`를 준다.

시간·저장은 호출측(service)이 주입한다 — 여기선 숫자만 보고 결정해 DB 없이 테스트한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.features.ratelimit.policy import Limit


@dataclass(frozen=True)
class Decision:
    """판정 결과. 거부면 `retry_after`(초) 후 재시도 가능."""

    allowed: bool
    retry_after: int = 0


def evaluate(limit: Limit, *, count: int, elapsed: float) -> Decision:
    """창 안 누적 `count`가 `limit.max_count` 이상이면 거부.

    - `count`      : 현재 창에서 지금까지 쌓인 수(요청 수 / 토큰 수 / 탈취 횟수).
    - `elapsed`    : 현재 창 시작 후 지난 초. 거부 시 `retry_after = 창 남은 시간`.
    증가분을 더하기 **전** 상태로 본다(= 이번 요청을 받으면 한도를 넘는가가 아니라, 이미 넘었는가).
    경계: `count >= max_count`면 거부(정확히 한도에 도달해도 막는다, fail-safe).
    """
    if count < limit.max_count:
        return Decision(allowed=True)
    remaining = limit.window_seconds - elapsed
    retry_after = max(0, math.ceil(remaining))
    # 창이 이미 지났으면(elapsed >= window) 리셋된 것 → 허용. 창 관리는 store가 하지만 방어적으로 한 번 더.
    if retry_after == 0:
        return Decision(allowed=True)
    return Decision(allowed=False, retry_after=retry_after)
