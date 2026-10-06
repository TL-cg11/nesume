from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import aws
from app.config import get_settings
from app.db import engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness: 프로세스 생존 여부만 확인한다. 외부 의존성 장애로 실패하지 않는다."""
    return {"status": "ok"}


@router.get("/ready")
def ready(response: Response) -> dict:
    """Readiness: DB(vector 확장 포함)와 S3 버킷 접근 가능 여부를 확인한다."""
    checks: dict[str, str] = {}

    try:
        with engine.connect() as conn:
            ext = conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
        checks["db"] = "ok"
        checks["vector"] = ext or "missing"
    except Exception as e:  # noqa: BLE001
        checks["db"] = f"error: {type(e).__name__}"

    bucket = get_settings().s3_bucket_name
    try:
        aws.client("s3").head_bucket(Bucket=bucket)
        checks["s3"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["s3"] = f"error: {type(e).__name__}"

    ok = checks.get("db") == "ok" and checks.get("vector") != "missing" and checks.get("s3") == "ok"
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ok else "degraded", "checks": checks}
