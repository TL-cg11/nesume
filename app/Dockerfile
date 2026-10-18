# --- base: 런타임 의존성 + 애플리케이션 코드 ---
FROM python:3.12.15-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app

RUN useradd --system --uid 10001 --no-create-home appuser

# --- test: 개발 의존성 추가. 운영 이미지에는 포함하지 않는다 ---
FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
USER appuser
CMD ["pytest"]

# --- runtime: 기본 빌드 대상(마지막 스테이지) ---
FROM base AS runtime
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
