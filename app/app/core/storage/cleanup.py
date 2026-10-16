"""다운로드 토큰 정리 배치 (B6). 1시간마다 실행: `python -m app.core.storage.cleanup`

운영에서는 K8s CronJob(D5)으로 스케줄링한다. 1회 실행당 최대 1,000행 삭제.
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
