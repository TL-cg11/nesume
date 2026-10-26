# nesume — 로컬 개발 환경

AI 자소서 작성·관리 서비스의 공통 Docker 개발 환경.

## 구성

| 서비스 | 이미지 | 역할 | 호스트 포트(기본) |
|---|---|---|---|
| web | `nginxinc/nginx-unprivileged:1.30.6-alpine` (React 19 + Vite 8 빌드) | 프론트엔드, `/api/*` → app 프록시 | `WEB_PORT` (8080) |
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
| `http://localhost:8000/health` | Liveness — 프로세스 생존만 확인. `version`(빌드 시 넣은 git sha, 로컬은 `dev`) 포함 |
| `http://localhost:8000/ready` | Readiness — DB, vector 확장, S3 버킷 확인 (실패 시 503) |
| `http://localhost:8000/docs` | API 문서 (`APP_ENV=local`·`test`일 때만) |

## 검증

```bash
# 1. /health 200. 응답 헤더에 X-Request-ID, 본문에 "version":"dev"
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
    core/            공통 모듈 (D3: request_id, errors, logging, health, aws)
    auth/            Cognito 토큰 검증 (B 초안, D7에서 확장)
    policy/          역할×등급 매트릭스 matrix.yaml + 로더 (C2)
    features/        기능 모듈 (resumes, experiences, ...)
  migrations/        Alembic 마이그레이션
  tests/             pytest
web/                 프론트엔드 (React + Vite, nginx)
infra/
  bootstrap/         Terraform: tfstate 버킷·잠금 테이블·ECR (D4, apply는 크레딧 뒤)
docs/dev/            개발 가이드 (backend-guide.md)
init/
  db/                DB 최초 기동 SQL (빈 볼륨일 때만 실행)
  localstack/        LocalStack ready 훅 (버킷·KMS 키·시크릿 생성, 매 기동 실행)
  cognito/db/        cognito-local user pool/client 시드 (고정 ID)
```

## 프론트엔드 개발 서버 (화면 수정 시)

```bash
cd web
npm ci
API_PROXY_TARGET=http://localhost:8080 npm run dev   # http://localhost:5173, /api는 nginx로 프록시
```

- `docker compose up -d`로 백엔드가 떠 있어야 한다.
- 로그인 화면(D7)이 들어왔다. `http://localhost:8080/login`에서 시드 계정으로 로그인한다(아래). DEV 토큰 입력란은 제거됐다.
- 시드 계정: `test-user1@example.com`(일반)·`test-mentor1@`(멘토)·`test-operator1@`(운영자)·`svc-batch@`(시스템). 비밀번호는 시드 시 준 `SEED_PASSWORD`. 그룹·계정은 시드 스크립트가 만든다: `docker compose run --rm -e SEED_PASSWORD='<pw>' test python -m app.auth.seed`
- web은 Cognito 설정을 빌드가 아니라 기동 시 `/config.json`(nginx가 치환)에서 읽는다. 로컬 로그인은 cognito-local 제약으로 `USER_PASSWORD_AUTH`, 운영은 SRP.
- 운영자 TOTP 강제(`OPERATOR_MFA_REQUIRED`)는 로컬에서 `false`(cognito-local TOTP 불완전). 토큰을 직접 발급해 API를 부르는 예:

```bash
H='Content-Type: application/x-amz-json-1.1'; C=nesumelocalclient00000001; E=dev@example.com; P='Dev!Passw0rd1'
curl -s -X POST localhost:9229/ -H "$H" -H 'X-Amz-Target: AWSCognitoIdentityProviderService.SignUp' \
  -d "{\"ClientId\":\"$C\",\"Username\":\"$E\",\"Password\":\"$P\",\"UserAttributes\":[{\"Name\":\"email\",\"Value\":\"$E\"}]}"
curl -s -X POST localhost:9229/ -H "$H" -H 'X-Amz-Target: AWSCognitoIdentityProviderService.AdminConfirmSignUp' \
  -d "{\"UserPoolId\":\"local_nesume\",\"Username\":\"$E\"}"
curl -s -X POST localhost:9229/ -H "$H" -H 'X-Amz-Target: AWSCognitoIdentityProviderService.InitiateAuth' \
  -d "{\"ClientId\":\"$C\",\"AuthFlow\":\"USER_PASSWORD_AUTH\",\"AuthParameters\":{\"USERNAME\":\"$E\",\"PASSWORD\":\"$P\"}}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["AuthenticationResult"]["AccessToken"])'
```

## 테스트

```bash
docker compose up -d                      # db, localstack, cognito가 healthy 상태여야 함
docker compose --profile test build test  # 최초 1회 또는 requirements 변경 시
docker compose run --rm test              # pytest 실행 (인자 전달 예: ... test pytest -k health)
```

- 테스트는 `app` 이미지의 `test` 스테이지(개발 의존성 포함)에서 실행된다. 운영 이미지(`runtime`)에는 pytest가 포함되지 않는다.
- `./app`을 읽기 전용으로 마운트하므로 코드 수정 후 재빌드 없이 바로 실행된다.
- 세션 시작 시 `<DB_NAME>_test` DB를 새로 만들고 마이그레이션을 적용하며, 종료 시 삭제한다. 개발 DB는 건드리지 않는다.
- 경고는 오류로 처리한다(`pytest.ini`의 `filterwarnings = error`).

## 마이그레이션

```bash
# 새 리비전 생성 (모델 정의 후 autogenerate)
docker compose run --rm migrate alembic revision --autogenerate -m "add resumes"
# 적용
docker compose run --rm migrate alembic upgrade head
```

- `vector` 확장 활성화의 기준은 첫 마이그레이션(`0001`)이다. `init/db`는 로컬 편의용이며 RDS에서는 실행되지 않는다.
- 생성된 리비전 파일은 컨테이너 내부에 생기므로 `docker compose cp` 또는 볼륨 마운트로 가져온다. 

## 로그 형식

- `LOG_FORMAT=json`(운영 기본): 한 줄 JSON. CloudWatch Logs에서 필드로 조회한다.
- `LOG_FORMAT=text`(로컬 권장): 사람이 읽기 쉬운 형식. `.env`에 넣으면 `docker compose logs app`이 읽기 편하다.
- `LOG_LEVEL`: 기본 `INFO`.
- 모든 줄에 `request_id`가 붙고, 요청 1건당 접근 로그 1줄(method, path, status, duration_ms)이 남는다. 요청 본문은 기록하지 않는다.
- 응답 헤더 `X-Request-ID`와 에러 본문의 `request_id`가 같은 값이다. 문의·로그 추적에 쓴다. 자세한 규칙은 `docs/dev/backend-guide.md`.

## 이미지 태그 규칙 (ECR)

- 저장소: `<ECR>/nesume/app`, `<ECR>/nesume/web`. `<ECR>`은 `<account>.dkr.ecr.ap-northeast-2.amazonaws.com`.
- 태그는 **git sha 하나**: `<ECR>/nesume/app:<git sha>`. `latest`·브랜치명 태그 금지. ECR은 `IMMUTABLE`이라 같은 태그를 덮어쓸 수 없다.
- 환경 승격(dev → staging → prod)은 재빌드가 아니라 **같은 sha를 Helm values의 `image.tag`에 적는 방식**으로 한다.
- 빌드 시 `--build-arg APP_VERSION=<git sha>`를 넣으면 `/health`의 `version`으로 어떤 빌드가 떠 있는지 확인할 수 있다. 로컬 빌드는 `dev`.

```bash
# 로컬에서 sha 태그로 빌드해 보기 (컨텍스트는 ./app, 저장소 루트가 아니다)
SHA=$(git rev-parse --short HEAD)
docker build -f app/Dockerfile --target runtime --build-arg APP_VERSION=$SHA -t nesume/app:$SHA ./app
docker run --rm -e APP_ENV=local -e DB_HOST=x -e DB_PORT=1 -e DB_NAME=x -e DB_USER=x -e DB_PASSWORD=x -p 8000:8000 nesume/app:$SHA
curl -s localhost:8000/health   # {"status":"ok","version":"<sha>"}
```

- ECR 생성·푸시는 AWS 크레딧 도착 후 `infra/bootstrap`(`terraform apply`)으로 저장소를 만들고 CI(D11)가 푸시한다. 그 전에는 `terraform init -backend=false && terraform validate`까지만 확인한다.
- 이미지 취약점 검사(Trivy). 수정판이 있는 HIGH/CRITICAL은 0이어야 한다. 나오면 베이스 이미지 패치 태그를 올리고 재빌드한다.

```bash
trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 nesume-app:local
trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 nesume-web:local
```

  `--ignore-unfixed`를 두는 이유: Debian 베이스(python:*-slim-bookworm)에는 배포판이 `will_not_fix`로 둔 CVE가 다수 있어 패치 태그를 올려도 사라지지 않는다. 전체 목록은 플래그를 빼고 본다.

## 운영 규칙

- 연결 정보는 전부 환경변수. 코드에 호스트 주소 하드코딩 금지.
- AWS SDK endpoint는 `AWS_ENDPOINT_URL`로만 지정. AWS 배포 시 미설정 → 실제 엔드포인트 사용.
- 이미지·패키지 버전 고정(`latest` 금지). 이미지 태그는 git sha(위 규칙).
- `.env`는 커밋 금지.

## 로컬 Cognito 제약 (cognito-local)

AWS 전환 시 처리할 항목:

- `USER_PASSWORD_AUTH`만 지원 → AWS에서는 `USER_SRP_AUTH`로 전환
- MFA는 SMS만 지원, TOTP 일부 구현 → TOTP MFA는 AWS 전환 후 검증
- `GlobalSignOut`·`AdminUserGlobalSignOut` 미지원 → 역할 변경(D6 `PUT /admin/users/{id}/role`)·계정 삭제 후 무효화는 로컬에서 `users.token_not_before`로만 동작. AWS에서 검증
- `client_credentials`(M2M) 미지원 → 시스템 토큰은 그룹 `system`의 서비스 계정(`svc-batch@`)이 USER_PASSWORD_AUTH로 받는다
- 역할 그룹(`mentor`/`operator`/`system`)과 `test` 그룹, 시드 계정 5개는 `init/cognito/db/`가 아니라 시드 스크립트가 만든다: `docker compose run --rm -e SEED_PASSWORD='<pw>' test python -m app.auth.seed` (볼륨 초기화 후 재실행)
- 확인 코드(가입·MFA)는 메일 대신 `docker compose logs cognito`에 출력됨
- 백엔드는 `COGNITO_ISSUER`(iss 검증)와 `COGNITO_JWKS_URL`(키 조회)을 분리해서 사용. `openid-configuration`은 주소가 고정되어 있어 사용하지 않는다.

## 초기화

```bash
docker compose down -v   # 볼륨(DB 데이터, cognito 사용자) 삭제
```
