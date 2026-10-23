"""애플리케이션 조립(D 소유).

- 미들웨어·예외 처리·로깅은 여기서만 붙인다.
- 기능 라우터는 명시적으로 include한다. 추가는 PR로 요청(커밋 메시지 [D 리뷰 요청]).
  접두사는 아직 없음(web이 /api/<기능> 호출).
"""
from fastapi import FastAPI

from app.config import get_settings
from app.core import health
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.core.request_id import RequestIdMiddleware
from app.core.storage.router import router as downloads_router
from app.features.applications.router import router as applications_router
from app.features.audit.router import router as audit_router
from app.features.experiences.router import links_router as experience_links_router
from app.features.experiences.router import router as experiences_router
from app.features.matching.router import router as matching_router
from app.features.profile.router import router as profile_router
from app.features.recommend.router import router as recommend_router
from app.features.resumes.router import router as resumes_router
from app.features.roadmap.router import router as roadmap_router
from app.features.style.router import router as style_router


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)

    application = FastAPI(
        title="nesume-api",
        version=settings.app_version,
        # API 문서는 로컬·테스트에서만 노출
        docs_url="/docs" if settings.is_local else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.is_local else None,
    )

    # 미들웨어는 바깥쪽부터: request_id가 가장 먼저 설정되어야 이후 로그·에러에 붙는다.
    application.add_middleware(RequestIdMiddleware)
    register_exception_handlers(application)

    application.include_router(health.router)
    application.include_router(resumes_router)
    application.include_router(experiences_router)
    application.include_router(experience_links_router)
    application.include_router(downloads_router)
    application.include_router(audit_router)
    application.include_router(applications_router)  # C15 지원 현황
    application.include_router(recommend_router)  # C8 공고 추천
    application.include_router(roadmap_router)  # C14 학습 로드맵
    # A 파트 2차 (A11 매칭 · A13 글자수·문체 · A14 말투 프로필) [D 리뷰 요청]
    application.include_router(matching_router)
    application.include_router(style_router)
    application.include_router(profile_router)
    return application


# B conftest의 client 픽스처와 uvicorn(app.main:app)이 이 이름을 쓴다. 반드시 남긴다.
app = create_app()
