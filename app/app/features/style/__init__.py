"""A13 — 글자 수·문체 조정.

    POST /style/adjust   글 + 제한 + 목표 문체  →  측정 · 규칙 제안 · 다시 쓴 글
    POST /style/apply    수락한 제안만 반영

## 이 기능에서 가장 중요한 판단 네 가지

**① 글자 수는 B4 와 같은 기준으로 센다** — `len(원문)`, 공백 포함. A13 이 "맞습니다"
라고 한 글이 저장할 때 제한을 넘으면 사용자는 A13 을 믿지 않는다. 저장된 본문은 PII
토큰화 상태라 세면 틀어지므로, 토큰이 섞인 글은 **거절한다** (`counter`).

**② 모델은 글자 수를 세지 못한다** — 응답을 받으면 **서버가 다시 센다.** 맞지 않으면
한 번 더 요청하고, 그래도 안 맞으면 버리고 이유를 돌려준다. 맞지도 않는 글을
"줄였습니다" 로 내보내면 사용자는 **저장 단계에서 거절당한다**.

**③ 새로 생긴 숫자가 있으면 통째로 버린다** — 자소서에서 가장 위험한 환각은 성과
수치다. 다시 쓰기는 글 전체가 바뀌므로 일부만 믿을 수 없다.

**④ 모자란 분량은 채워 주지 않는다** — 최소 글자 수에 미치면 **질문만** 돌려준다.
A7(STAR 보완)·A11(빠진 요건)과 같은 판단이다.

## A7 과 겹치지 않는다

| | 보는 것 | 규칙 접두어 |
| --- | --- | --- |
| **A7** | 맞춤법·띄어쓰기·이중피동·상투어·긴 문장·STAR | `WR_` |
| **A13** | **글자 수 · 문체 통일** | `ST_` |

문체 혼용("~합니다"와 "~해요"가 섞임)은 맞춤법 검사로 잡히지 않는다 — 둘 다 맞는
문장이기 때문이다. 그래서 A13 이 따로 본다.
"""

from app.features.style.counter import (
    COUNT_BASIS,
    CharCount,
    TokenizedTextError,
    count,
)
from app.features.style.length import (
    RULE_PREFIX,
    Confidence,
    OverlappingTrims,
    StaleTrim,
    Trim,
    apply_trims,
    find_trims,
    savings,
)
from app.features.style.service import (
    FEATURE,
    MAX_REWRITE_ATTEMPTS,
    NO_INVENTION_NOTICE,
    SHORT_QUESTIONS,
    AdjustResult,
    Rewrite,
    adjust,
    clean_reply,
    invented_numbers,
    numbers_in,
    verify_rewrite,
)
from app.features.style.tone import (
    DEFAULT_TONE,
    TONE_NAMES,
    TONES,
    Sentence,
    Tone,
    ToneAnalysis,
    analyze,
    ending_tone,
)

__all__ = [
    # 세기
    "count",
    "CharCount",
    "COUNT_BASIS",
    "TokenizedTextError",
    # 문체
    "analyze",
    "ending_tone",
    "ToneAnalysis",
    "Sentence",
    "Tone",
    "TONES",
    "TONE_NAMES",
    "DEFAULT_TONE",
    # 줄이기
    "find_trims",
    "apply_trims",
    "savings",
    "Trim",
    "Confidence",
    "StaleTrim",
    "OverlappingTrims",
    "RULE_PREFIX",
    # 조립
    "adjust",
    "AdjustResult",
    "Rewrite",
    "verify_rewrite",
    "numbers_in",
    "invented_numbers",
    "clean_reply",
    "NO_INVENTION_NOTICE",
    "SHORT_QUESTIONS",
    "MAX_REWRITE_ATTEMPTS",
    "FEATURE",
]
