"""다운로드 토큰 정리 배치 (B6). 실행: `python -m app.core.storage.cleanup`

실행 주기는 1시간, 1회 최대 1,000행 삭제. 자동 실행(K8s CronJob 등)은 보류 중(part2_guide 4.24).
"""
from app.core.storage import tokens
from app.db import SessionLocal


def main() -> int:
    with SessionLocal() as db:
        deleted = tokens.cleanup(db)
        db.commit()
    print(f"download_tokens cleanup: deleted={deleted}")
    return deleted


if __name__ == "__main__":
    main()
