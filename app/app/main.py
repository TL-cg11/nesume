from fastapi import FastAPI

from app.config import get_settings
from app.features.experiences.router import links_router as experience_links_router
from app.features.experiences.router import router as experiences_router
from app.features.resumes.router import router as resumes_router
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
app.include_router(resumes_router)
app.include_router(experiences_router)
app.include_router(experience_links_router)
