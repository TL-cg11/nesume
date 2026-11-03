# --- base: 런타임 의존성 + 애플리케이션 코드 ---
FROM python:3.12.16-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 베이스 이미지의 Debian 보안 패치를 당긴다. CI(D11) trivy 가 HIGH/CRITICAL 로 배포를 막는다(10-28: openssl CVE-2026-84782).
# 이 레이어는 GHA 캐시에 남으므로 새 CVE 가 나오면 캐시를 비우거나 이 줄을 건드려 재빌드한다.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-nanum && rm -rf /var/lib/apt/lists/*

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
# C16 NeMo 의도 레일(guardrails_nemo/, docs/C16.md). runtime 에만 — test 스테이지 시험은 가짜 판정기로 돈다.
# 켜는 것은 NEMO_QUERY_MODE·NEMO_CHUNK_MODE(기본 off). 모델은 받지 않는다(임베딩은 우리 bge-m3 서비스).
COPY requirements-nemo.txt .
RUN pip install --no-cache-dir -r requirements-nemo.txt
# CI(D11)가 --build-arg APP_VERSION=<git sha>로 넣는다. /health의 version으로 배포 확인. test 스테이지에는 넣지 않는다.
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
