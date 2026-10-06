from fastapi import FastAPI

from app.config import get_settings
from app.routers import health

settings = get_settings()

app = FastAPI(
    title="nesume-api",
    # API 문서는 로컬에서만 노출
    docs_url="/docs" if settings.app_env == "local" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.app_env == "local" else None,
)

app.include_router(health.router)
