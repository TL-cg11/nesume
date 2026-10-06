# nesume — 로컬 개발 환경

AI 자소서 작성·관리 서비스의 공통 Docker 개발 환경.

## 구성

| 서비스 | 이미지 | 역할 | 호스트 포트(기본) |
|---|---|---|---|
| web | `nginxinc/nginx-unprivileged:1.30.5-alpine` (React 19 + Vite 8 빌드) | 프론트엔드, `/api/*` → app 프록시 | `WEB_PORT` (8080) |
| app | `python:3.12.15-slim-bookworm` (FastAPI + SQLAlchemy 2.0 + Alembic) | 백엔드 API | `APP_PORT` (8000) |
| migrate | app 이미지 | `alembic upgrade head` 1회 실행 후 종료 | — |
| db | `pgvector/pgvector:0.8.7-pg16-bookworm` | PostgreSQL 16 + pgvector | **노출 안 함** |
| localstack | `localstack/localstack:2026.09.0` | S3, KMS, Secrets Manager | `LOCALSTACK_PORT` (4566) |
| cognito | `jagregory/cognito-local:5.3.0` | Cognito 대체(로컬 전용) | `COGNITO_PORT` (9229) |

호스트 포트는 `HOST_BIND_IP`(기본 `127.0.0.1`)에만 바인딩되어 같은 네트워크의 다른 장비에서 접근할 수 없다.

기동 순서: `db` → `migrate` → (`localstack`, `cognito`) → `app` → `web`. 각 단계는 healthcheck 통과 후 진행한다.

## 사전 준비

1. Docker Desktop(Compose v2 이상)
2. **LocalStack Auth Token** — LocalStack 이미지는 토큰 없이 기동되지 않는다.
   [app.localstack.cloud](https://app.localstack.cloud) 가입(비상업 무료 플랜) → Auth Token 발급. 토큰은 개인별이며 공유 금지.

## 실행

```bash
cp .env.example .env
# .env 값 채우기(아래 예시 참고). LOCALSTACK_AUTH_TOKEN, DB_PASSWORD는 각자 설정.
docker compose up -d --build
docker compose ps
```

### .env 로컬 예시

```dotenv
APP_ENV=local
HOST_BIND_IP=127.0.0.1

WEB_PORT=8080
APP_PORT=8000
LOCALSTACK_PORT=4566
COGNITO_PORT=9229

DB_NAME=nesume
DB_USER=nesume
DB_PASSWORD=<임의의 강한 값>

LOCALSTACK_AUTH_TOKEN=<개인 토큰>
AWS_REGION=ap-northeast-2
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
S3_BUCKET_NAME=nesume-local-docs
KMS_KEY_ALIAS=alias/nesume-local-pii
APP_SECRET_NAME=nesume/local/app

COGNITO_ISSUER_DOMAIN=http://localhost:9229
COGNITO_USER_POOL_ID=local_nesume
COGNITO_CLIENT_ID=nesumelocalclient00000001
```

`COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`는 `init/cognito/db/`의 시드와 일치해야 한다(팀 공통 고정값).

## 엔드포인트

| URL | 설명 |
|---|---|
| `http://localhost:8080` | 프론트엔드 |
| `http://localhost:8080/api/health` | 프론트 경유 health |
| `http://localhost:8000/health` | Liveness — 프로세스 생존만 확인 |
| `http://localhost:8000/ready` | Readiness — DB, vector 확장, S3 버킷 확인 (실패 시 503) |
| `http://localhost:8000/docs` | API 문서 (`APP_ENV=local`일 때만) |

## 검증

```bash
# 1. /health 200
curl -i http://localhost:8000/health

# 2. vector 확장 활성화
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT extname, extversion FROM pg_extension WHERE extname = '\''vector'\'';"'

# 3. LocalStack 버킷 생성
docker compose exec localstack awslocal s3 ls
```

## 디렉터리

```
app/                 백엔드 (FastAPI)
  app/               애플리케이션 패키지
  migrations/        Alembic 마이그레이션
web/                 프론트엔드 (React + Vite, nginx)
init/
  db/                DB 최초 기동 SQL (빈 볼륨일 때만 실행)
  localstack/        LocalStack ready 훅 (버킷·KMS 키·시크릿 생성, 매 기동 실행)
  cognito/db/        cognito-local user pool/client 시드 (고정 ID)
```

## 마이그레이션

```bash
# 새 리비전 생성 (모델 정의 후 autogenerate)
docker compose run --rm migrate alembic revision --autogenerate -m "add resumes"
# 적용
docker compose run --rm migrate alembic upgrade head
```

- `vector` 확장 활성화의 기준은 첫 마이그레이션(`0001`)이다. `init/db`는 로컬 편의용이며 RDS에서는 실행되지 않는다.
- 생성된 리비전 파일은 컨테이너 내부에 생기므로 `docker compose cp` 또는 볼륨 마운트로 가져온다. 

## 운영 규칙

- 연결 정보는 전부 환경변수. 코드에 호스트 주소 하드코딩 금지.
- AWS SDK endpoint는 `AWS_ENDPOINT_URL`로만 지정. AWS 배포 시 미설정 → 실제 엔드포인트 사용.
- 이미지·패키지 버전 고정(`latest` 금지).
- `.env`는 커밋 금지.

## 로컬 Cognito 제약 (cognito-local)

AWS 전환 시 처리할 항목:

- `USER_PASSWORD_AUTH`만 지원 → AWS에서는 `USER_SRP_AUTH`로 전환
- MFA는 SMS만 지원, TOTP 일부 구현 → TOTP MFA는 AWS 전환 후 검증
- `GlobalSignOut` 미지원 → 계정 삭제 후 토큰 무효화는 AWS에서 검증
- 확인 코드(가입·MFA)는 메일 대신 `docker compose logs cognito`에 출력됨
- 백엔드는 `COGNITO_ISSUER`(iss 검증)와 `COGNITO_JWKS_URL`(키 조회)을 분리해서 사용. `openid-configuration`은 주소가 고정되어 있어 사용하지 않는다.

## 초기화

```bash
docker compose down -v   # 볼륨(DB 데이터, cognito 사용자) 삭제
```
