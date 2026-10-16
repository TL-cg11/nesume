"""B 문서 공용 PII 처리 지점 (part2_guide 4.6, 4.8, 5.3).

자소서 본문·경험 데이터는 PII 토큰화 상태로 저장한다. 토큰화·민감정보 판정(A1)과
매핑 저장소(B7)가 준비되기 전까지 아래 함수는 입력을 그대로 통과시킨다.
추합 시 이 파일의 구현만 교체한다.
"""


class SensitiveInputBlocked(ValueError):
    """주민번호·계좌번호 등 저장이 금지된 민감정보가 포함됨(A1 판정)."""


def ensure_no_sensitive(text: str) -> None:
    """민감정보가 있으면 SensitiveInputBlocked를 발생시킨다(B5 "민감정보 차단")."""
    return None


def tokenize_for_storage(owner_id: str, text: str) -> str:
    """저장 직전: PII를 [PHONE_1] 같은 토큰으로 치환하고 매핑을 B7 저장소에 기록한다."""
    return text


def restore_for_owner(owner_id: str, requester_id: str, text: str) -> str:
    """소유자 본인에게 보여줄 때만 토큰을 원문으로 복원한다(tasks B7)."""
    return text
