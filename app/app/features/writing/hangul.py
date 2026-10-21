"""한글 음절 판별 헬퍼.

A1 의 조사 보정에도 같은 계산이 있다. 거기서 가져다 쓰지 않고 여기 다시 적은 이유는,
글 교정 기능이 개인정보 모듈을 import 하게 되는 쪽이 더 이상하기 때문이다.
식(유니코드 산술)은 바뀌지 않는 값이라 중복의 위험이 낮다.
나중에 공용 유틸 모듈이 생기면 양쪽을 그쪽으로 옮긴다.
"""

from __future__ import annotations

_BASE = 0xAC00
_LAST = 0xD7A3
_JONG = 28
_RIEUL = 8  # 종성 ㄹ


def is_hangul_syllable(ch: str) -> bool:
    return bool(ch) and _BASE <= ord(ch) <= _LAST


def has_final_consonant(ch: str) -> bool:
    """받침이 있는가."""
    if not is_hangul_syllable(ch):
        return False
    return (ord(ch) - _BASE) % _JONG != 0


def has_rieul_final(ch: str) -> bool:
    """받침이 ㄹ인가. '으로/로' 선택에 쓴다."""
    if not is_hangul_syllable(ch):
        return False
    return (ord(ch) - _BASE) % _JONG == _RIEUL
