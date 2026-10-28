"""A7 — 맞춤법·문장 개선 + STAR 변환.

    from app.features.writing import improve, check, analyze, apply_suggestions

    result = await improve(text, guard=guard, user_id=..., role=...)
    result.suggestions    # 제안 목록 (항목마다 id 가 있어 수락·거절을 추적)
    result.star           # STAR 요소 분석
    result.llm_used       # 2차를 돌렸는가

    final = apply_suggestions(text, result.suggestions, accepted=["a1b2c3", ...])

A6 리라이팅은 `rewrite` / `apply_candidate` 입니다.

    from app.features.writing import rewrite, RewriteOptions

    result = await rewrite(db, text, RewriteOptions(tone="formal"), guard=..., store=...)
    result.candidates     # 후보 3개. 각각 body 와 원문 대비 segments
    result.instructions   # 모델에 간 지시문 (무엇이 갔는지 사용자가 본다)

설계 두 가지를 기억하면 됩니다.

1. **규칙이 먼저, 모델은 나중.** 규칙은 싸고 결과가 항상 같고 근거를 댈 수 있습니다.
   모델에는 문맥이 필요한 것만 맡깁니다.
2. **STAR 요소가 2개 이하면 모델에게 맡기지 않습니다.** 빈칸이 많은 글을 모델에
   주면 없는 경험을 지어냅니다. 대신 무엇이 빠졌는지 질문으로 돌려줍니다.
"""

from app.features.writing.hangul import has_final_consonant, has_rieul_final
from app.features.writing.proofread import MAX_SENTENCE_LEN, RULES, check
from app.features.writing.rewrite import (
    CANDIDATE_COUNT,
    MAX_CHUNK_CHARS,
    MAX_KEYWORDS,
    MAX_SELECTION_LEN,
    RewriteOptionError,
    RewriteOptions,
    normalize_keywords,
)
from app.features.writing.rewrite_service import (
    TEMPLATE_NAME,
    Candidate,
    RewriteResult,
    apply_candidate,
    rewrite,
)
from app.features.writing.schemas import MAX_TEXT_LEN
from app.features.writing.service import (
    FEATURE,
    MAX_LLM_SUGGESTIONS,
    SEP,
    ImproveResult,
    improve,
    parse_llm_suggestions,
)
from app.features.writing.star import (
    ELEMENT_NAMES,
    STAR_ELEMENTS,
    StarAnalysis,
    StarElement,
    analyze,
    guidance,
)
from app.features.writing.suggestions import (
    Confidence,
    OverlappingSuggestions,
    StaleSuggestion,
    Suggestion,
    SuggestionKind,
    apply_suggestions,
)

__all__ = [
    "improve", "ImproveResult", "FEATURE", "SEP", "MAX_LLM_SUGGESTIONS",
    "parse_llm_suggestions",
    "check", "RULES", "MAX_SENTENCE_LEN", "MAX_TEXT_LEN",
    "analyze", "guidance", "StarAnalysis", "StarElement", "STAR_ELEMENTS",
    "ELEMENT_NAMES",
    "Suggestion", "SuggestionKind", "Confidence", "apply_suggestions",
    "OverlappingSuggestions", "StaleSuggestion",
    "has_final_consonant", "has_rieul_final",
    # A6 리라이팅
    "rewrite", "apply_candidate", "RewriteResult", "Candidate",
    "RewriteOptions", "RewriteOptionError", "normalize_keywords",
    "CANDIDATE_COUNT", "MAX_CHUNK_CHARS", "MAX_SELECTION_LEN", "MAX_KEYWORDS",
    "TEMPLATE_NAME",
]
