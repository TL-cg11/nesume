"""본문 PII 처리 지점 (part2_guide 5.3).

본문은 PII 토큰화 상태로 저장하기로 결정했다. 토큰화(A1)와 매핑 저장소(B7)가 준비되기 전까지
두 함수는 입력을 그대로 반환한다. 추합 시 이 파일의 구현만 교체한다.
"""


def tokenize_for_storage(owner_id: str, text: str) -> str:
    """저장 직전: PII를 [PHONE_1] 같은 토큰으로 치환하고 매핑을 B7 저장소에 기록한다."""
    return text


def restore_for_owner(owner_id: str, requester_id: str, text: str) -> str:
    """소유자 본인에게 보여줄 때만 토큰을 원문으로 복원한다(tasks B7)."""
    return text
