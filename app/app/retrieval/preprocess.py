"""C5 — 외부 텍스트 지시문 제거 전처리 (prompt-injection 1차 방어).

외부 untrusted 텍스트(공고 본문·붙여넣은 공고·GitHub README)를 LLM에 "데이터"로
넣기 전에 (1) 정규화 (2) 길이 상한 (3) 인젝션 패턴 중화+플래그 를 수행한다.

방어는 다층이다. 이 모듈은 한 겹일 뿐 — 구조적 데이터/지시 구분은 A8,
출력 재검사는 A5가 담당한다. "인젝션 완전 차단"으로 과신하지 않는다.
PII 처리는 A1 소관이며 여기서 하지 않는다(공고는 A1 마스킹 뒤에 C5가 돈다).

순수 stdlib(re, unicodedata). 외부 의존 없음.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# 매칭된 지시 문구를 대체할 중화 마커 (삭제가 아니라 무력화 — 설계 (b))
NEUTRALIZED = "⟦무력화된 지시⟧"

DEFAULT_MAX_LEN = 8000

# (rule_id, 정규식). 오탐을 줄이려고 단어 하나가 아니라 구(句) 단위로만 잡는다.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # 이전 지시 무시류 — "지시/명령/지침" 과 "무시/무효" 사이에 단어가 끼어도 잡도록 창(window) 방식
    ("R-OVERRIDE", re.compile(r"(지시|명령|지침)[\w\s]{0,12}?(무시|무효)", re.I)),
    ("R-OVERRIDE", re.compile(
        r"(ignore|disregard|forget)\s+[\w\s]{0,20}?(instruction|prompt|direction|rule|context)s?", re.I)),
    ("R-OVERRIDE", re.compile(r"disregard\s+(the\s+)?(above|previous|prior|earlier)", re.I)),
    # 역할 탈취
    ("R-ROLE", re.compile(r"(지금부터|이제부터|이제)\s*(너는|당신은|넌)", re.I)),
    ("R-ROLE", re.compile(r"개발자\s*모드|developer\s+mode|jailbreak", re.I)),
    ("R-ROLE", re.compile(r"\byou\s+are\s+now\b|\bact\s+as\s+an?\b", re.I)),
    ("R-ROLE", re.compile(r"^\s*(system|assistant)\s*:", re.I | re.M)),
    # 시스템 프롬프트·내부 규칙 추출
    ("R-SYSPROMPT", re.compile(r"시스템\s*프롬프트|system\s+prompt", re.I)),
    ("R-SYSPROMPT", re.compile(r"(프롬프트|지침|규칙)[을를]?\s*(출력|공개|보여|알려)", re.I)),
    ("R-SYSPROMPT", re.compile(
        r"(reveal|print|show|repeat)\s+(your\s+|the\s+)?(system\s+)?(prompt|instruction)s?", re.I)),
    # 대량 유출 유도
    ("R-EXFIL", re.compile(r"모든\s*(문서|데이터|기록|파일)[을를]?\s*(나열|출력|보여|공개)", re.I)),
    ("R-EXFIL", re.compile(r"list\s+all\s+(document|file|record|data)s?", re.I)),
    # 구분자/마크업 깨기 (데이터 블록 탈출 시도)
    ("R-DELIM", re.compile(r"`{3,}")),
    ("R-DELIM", re.compile(r"</?(system|assistant|user|im_start|im_end)\b[^>]*>", re.I)),
]


@dataclass
class PreprocessResult:
    text: str                       # 정제·중화된 텍스트 (LLM에 넣을 값)
    flags: list[str] = field(default_factory=list)   # 탐지 신호(rule_id) — 감사 로그·대시보드용
    truncated: bool = False         # 길이 상한으로 잘렸는지


def _has_hidden_chars(s: str) -> bool:
    """제어문자(Cc)·포맷문자(Cf: 제로폭·BOM·소프트하이픈 등)가 있으면 True. \\n \\t 는 제외."""
    for ch in s:
        if ch in "\n\t":
            continue
        if unicodedata.category(ch) in ("Cc", "Cf"):
            return True
    return False


def _strip_hidden_chars(s: str) -> str:
    """제어·포맷·사용자정의·대리 문자를 제거. \\n \\t 는 보존."""
    return "".join(
        ch for ch in s
        if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf", "Co", "Cs")
    )


def preprocess_external_text(text: str | None, *, max_len: int = DEFAULT_MAX_LEN) -> PreprocessResult:
    """외부 텍스트를 LLM 입력용으로 전처리한다.

    단계: ① 숨김문자 탐지 ② NFKC 정규화 + 숨김문자 제거 ③ 인젝션 패턴 중화+플래그
          ④ 공백·개행 축소 ⑤ 길이 상한.
    """
    flags: list[str] = []

    if not isinstance(text, str) or not text:
        return PreprocessResult(text="", flags=[], truncated=False)

    # ① 숨김문자 탐지 (정규화 전 원본 기준) — 호모글리프·제로폭 우회 신호
    if _has_hidden_chars(text):
        flags.append("HIDDEN_CHARS")

    # ② NFKC 정규화(전각·일부 변형 문자 통일) 후 숨김문자 제거
    t = unicodedata.normalize("NFKC", text)
    t = _strip_hidden_chars(t)

    # ③ 인젝션 패턴 중화(defang) + 플래그. 본문은 지우지 않고 매칭 부분만 마커로 치환
    for rule_id, pattern in _INJECTION_PATTERNS:
        if pattern.search(t):
            t = pattern.sub(NEUTRALIZED, t)
            if rule_id not in flags:
                flags.append(rule_id)

    # ④ 공백·개행 축소
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = t.strip()

    # ⑤ 길이 상한
    truncated = False
    if len(t) > max_len:
        t = t[:max_len].rstrip()
        truncated = True

    return PreprocessResult(text=t, flags=flags, truncated=truncated)
