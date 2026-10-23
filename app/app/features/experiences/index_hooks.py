"""개인 인덱스 반영 지점 (tasks B5 "저장 후 C3로 개인 인덱스 반영").

C3(임베딩 파이프라인, C팀)이 준비되기 전까지 아무 동작도 하지 않는다. 추합 시 이 파일만 교체한다.
C3 운영 Embedder(D 서빙)가 정해지면 연결한다. 소프트 삭제 반영은 service에서 C3 mark_personal_deleted 호출.
"""
import uuid


def index_experience(owner_id: str, experience_id: uuid.UUID) -> None:
    """등록·수정 후 호출. C3가 토큰화된 경험 데이터를 개인 인덱스에 저장한다."""
    return None
