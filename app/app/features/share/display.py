"""멘토에게 보여줄 본문 표시 (spec 3.7 "공유 문서에 포함된 PII는 마스킹 상태로만 표시", part2_guide 4.44).

저장된 본문은 A1 토큰(`[[PHONE_1]]`) 상태다. 멘토에게는 원문 복원 없이, 토큰을 읽기 쉬운 문구로 바꿔 보여준다.
번호는 지운다(멘토가 같은 사람·다른 사람을 구분할 필요가 없고, 번호도 문서 구조 정보라 드러내지 않는다).
"""
import re

# A1 토큰 형식([[KIND_N]], app/app/pii/tokens.py)과 같은 모양. A1 내부 상수를 import하지 않는다
_TOKEN = re.compile(r"\[\[([A-Z]+)_\d+\]\]")

KIND_TEXT = {
    "PERSON": "이름",
    "ORG": "기관명",
    "SCHOOL": "학교명",
    "PHONE": "전화번호",
    "EMAIL": "이메일",
    "ADDRESS": "주소",
}


def readable(text: str) -> str:
    """`연락처 [[PHONE_1]]` → `연락처 (전화번호 비공개)`. 모르는 종류는 `(비공개 정보)`."""
    return _TOKEN.sub(lambda m: f"({KIND_TEXT[m.group(1)]} 비공개)" if m.group(1) in KIND_TEXT else "(비공개 정보)",
                      text)
