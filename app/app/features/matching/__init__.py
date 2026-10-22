"""A11 — 공고 키워드 추출 + 매칭 분석.

공고가 요구하는 것을 뽑아 **사용자가 이미 쓴 글·가진 경험과 대조**한다.

    POST /matching/analyze   공고 + 자소서 + 경험  →  요건별 대조 결과

## 흐름

    1. 공고 준비    A1 mask → C5 preprocess        docs/C5.md 가 정한 순서
    2. 키워드 추출  구조화 필드는 구분자, 줄글은 사전   LLM 없음
    3. 대조         covered / in_experience_only / missing
    4. 질문 생성    빠진 요건 → 질문                규칙만
    5. 반영 문장    경험에만 있는 것 → 한 문장        A8 경유 (선택)

## 이 기능에서 가장 중요한 판단 두 가지

**① 빠진 요건에는 문장을 만들지 않는다.** 질문만 돌려준다. 매칭 분석의 가장 큰 위험은
**허위 기재 유도**다 — "Python 이 빠졌습니다" 다음에 예시 문장을 붙이면 사용자는
해 본 적 없는 일을 쓴다. 자소서의 허위 기재는 면접에서 드러나고 **책임은 사용자가 진다.**

**② 모델이 없는 기술을 끼워 넣으면 버린다.** "Docker 로 배포했습니다" 를 만들라고 했는데
"Docker 와 Kubernetes 로" 가 돌아오는 것을 그냥 쓰면 쓴 적 없는 기술이 자소서에 들어간다.
`service.parse_hints` 가 사용자 글·경험에 없는 사전 항목이 문장에 나오면 버리고,
버린 개수를 `dropped_hints` 로 돌려준다 — **측정할 수 있게 남긴다.**

## 남의 테이블을 읽지 않는다

공고는 C4, 자소서·경험은 B 소유다. 어느 함수로 읽을지 협의되기 전에는
**호출자가 값을 넘기는 방식**으로 둔다 (`schemas.py` 주석). 그래서 이 패키지는
DB 드라이버 없이 테스트된다.
"""

from app.features.matching.coverage import (
    MIN_KEYWORDS_FOR_RATE,
    STATUSES,
    CoverageReport,
    ExperienceRef,
    Match,
    UserEvidence,
    compare,
)
from app.features.matching.keywords import (
    IMPORTANCES,
    MAX_FRAGMENT_LEN,
    Keyword,
    PostingFields,
    extract,
)
from app.features.matching.service import (
    FEATURE,
    MAX_HINTS,
    NO_INVENTION_NOTICE,
    SEP,
    AnalyzeResult,
    Hint,
    PreparedPosting,
    analyze,
    parse_hints,
    prepare_posting,
    questions_for,
)
from app.features.matching.vocab import CATEGORIES, TERMS, Term, found_in, matched_keys, scan, squash

__all__ = [
    # 키워드 추출
    "extract",
    "Keyword",
    "PostingFields",
    "IMPORTANCES",
    "MAX_FRAGMENT_LEN",
    # 대조
    "compare",
    "CoverageReport",
    "Match",
    "UserEvidence",
    "ExperienceRef",
    "STATUSES",
    "MIN_KEYWORDS_FOR_RATE",
    # 조립
    "analyze",
    "AnalyzeResult",
    "Hint",
    "prepare_posting",
    "PreparedPosting",
    "questions_for",
    "parse_hints",
    "NO_INVENTION_NOTICE",
    "FEATURE",
    "SEP",
    "MAX_HINTS",
    # 사전
    "TERMS",
    "Term",
    "CATEGORIES",
    "scan",
    "matched_keys",
    "found_in",
    "squash",
]
