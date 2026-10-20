# 백엔드 개발 가이드 (D3)

`app/` 아래에서 기능을 추가할 때 지켜야 하는 공통 규칙이다. B가 선행 작성한 골격(`db.py`, `conftest.py`, `Dockerfile`, 라우터 등록)을 기준으로 D가 공통 에러 형식·request_id·구조화 로깅·설정을 얹었다.

## 1. 구조와 소유

```
app/app/
  main.py          앱 조립(D). 미들웨어·예외 핸들러·로깅·라우터 등록은 여기서만
  config.py        환경변수 설정(D). 새 변수는 D에 요청
  db.py            엔진·세션·Base·get_db (B 작성, D 소유. 수정 시 B와 합의)
  auth/            Cognito 토큰 검증·CurrentUser (B 초안, D7에서 확장)
  core/            공통 모듈(D): context, request_id, errors, schemas, logging, aws, health
  core/storage/    S3 비공개 저장·다운로드 토큰 (B6)
  features/        기능 모듈 (B: resumes, experiences / A·C 추가 예정)
  models/          ORM 모델 취합 (B)
  policy/          역할×등급 매트릭스 matrix.yaml + 로더 (C2, 파일 소유는 D)
  retrieval/       검색 전처리 (C)
app/migrations/    Alembic 리비전 (B 취합)
app/tests/         pytest. conftest·pytest.ini는 B 작성
```

소유 표는 `docs/tasks.md`가 기준이다. **다른 팀 소유 경로는 PR로 요청**하고 직접 고치지 않는다.

## 2. 기능 모듈 추가 절차

1. `features/<기능>/` 패키지를 만들고 `router.py`에 `router = APIRouter(prefix="/<기능>", tags=["<기능>"])`를 둔다.
2. 스키마는 `schemas.py`, 저장소 접근은 `repository.py`, 비즈니스 로직은 `service.py`로 나눈다(B 모듈 구조 참고).
3. `main.py` 등록은 D에 PR로 요청한다. 커밋 메시지에 `[D 리뷰 요청]`을 넣는다.
4. 접두사 `/v1`은 붙이지 않는다. web이 `/api/<기능>`으로 호출하고 nginx가 `/api/`를 떼어 app으로 넘긴다.
5. 라우터 자동 등록은 쓰지 않는다(모듈당 라우터가 2개인 경우가 있어 규칙이 맞지 않음). A·C 기능이 붙을 때 재검토한다.

## 3. 에러 규칙

- 기존 코드의 `HTTPException(detail=...)`은 그대로 둬도 된다. FastAPI 기본 응답 `{"detail": "..."}`이 나간다.
- 새 코드는 `app.core.errors`의 `AppError` 계열을 권장한다.

| 클래스 | status | code |
|---|---|---|
| `AppError` | 400 | `bad_request` |
| `UnauthorizedError` | 401 | `unauthorized` |
| `ForbiddenError` | 403 | `forbidden` |
| `NotFoundError` | 404 | `not_found` |
| `ConflictError` | 409 | `conflict` |
| `RateLimitedError` | 429 | `rate_limited` |

응답 형식(평면):

```json
{"detail": "자소서를 찾을 수 없습니다.", "code": "not_found", "request_id": "3f2a...", "errors": null}
```

- 두 경우 모두 응답에 `detail`이 있다. web `ApiError`는 `detail`만 읽는다.
- 422(검증 실패)는 `code: validation_error`이고 `errors`에 `type`·`loc`·`msg`만 담는다. **입력 원문(`input`)은 넣지 않는다**(자소서 본문·주민번호가 응답·로그에 남는 것을 막는다).
- 500은 고정 메시지(`internal_error`)만 내보내고 스택은 로그에만 남는다.
- 검증 상세 키 이름이 `errors`인 이유: 경험 데이터 모델에 `detail` 도메인 필드가 있어 `details`와 헷갈린다.

## 4. request_id

- 모든 요청에 `X-Request-ID`가 붙는다. 클라이언트가 보낸 값이 `[A-Za-z0-9._:-]{1,128}`이면 그대로 쓰고, 아니면 새로 만든다(uuid4 hex).
- 코드에서는 `from app.core.context import get_request_id`로 읽는다. 감사 로그(B3/B11)의 `request_id` 컬럼에 이 값을 쓴다.
- 접근 로그는 미들웨어가 요청당 1줄(method, path, status, duration_ms, client_ip) 남긴다. **질의 본문·요청 바디는 로그에 남기지 않는다.**

## 5. DB

- 핸들러에서는 `db: Session = Depends(get_db)`(또는 `Annotated[Session, Depends(get_db)]`)로 세션을 받는다.
- `get_db`는 핸들러가 **정상 종료하면 자동 commit, 예외면 rollback**한다(B 구현). 중간 commit이 필요하면(예: 토큰 사용 처리를 먼저 확정) 명시적으로 `db.commit()`을 호출한다.
- 모델은 `app/app/models/`에 B가 취합한다. 제약 이름은 `Base.metadata`의 `NAMING_CONVENTION`으로 자동 생성되므로 이름을 직접 쓰지 않는다.
- 마이그레이션은 `docker compose run --rm migrate alembic revision --autogenerate -m "..."`로 만든다(README).

## 6. 설정·로깅

- 설정은 `from app.config import get_settings`로 읽는다. 새 환경변수가 필요하면 D에 요청한다(`config.py`, `docker-compose.yml`, `.env.example`, Helm values를 함께 고쳐야 한다).
- `APP_ENV`는 `local|test|dev|staging|production`만 허용. `settings.is_local`(local·test)에서만 `/docs`가 열린다.
- 로거는 `logging.getLogger("nesume.<모듈>")`. 추가 필드는 `extra={"fields": {...}}`로 넘긴다.

```python
log = logging.getLogger("nesume.resumes")
log.info("resume_created", extra={"fields": {"resume_id": str(resume.id)}})
```

- `LOG_FORMAT=json`(운영 기본)이면 한 줄 JSON, `text`(로컬 권장)면 읽기 쉬운 형식. 모든 줄에 `request_id`가 붙는다.
- **비밀값·PII·자소서 본문은 로그에 넣지 않는다.**

## 7. 인증

- `from app.auth import AuthenticatedUser`를 핸들러 파라미터로 받는다(B 초안). `user.sub`, `user.role`을 쓴다.
- D7에서 `require_role`, 운영자 MFA 세션 확인, system 토큰을 추가한다. `CurrentUser`·`get_current_user` 인터페이스는 유지된다.
- 인증 실패 응답은 FastAPI 기본 `{"detail": "Not authenticated"}`를 유지한다.

## 8. LLM 호출 규칙

- 외부 LLM(Bedrock 등) 호출은 A8의 공용 클라이언트만 사용한다. 다른 경로에서 SDK를 직접 호출하지 않는다. CI(D11)가 grep으로 검사한다.

## 9. 테스트

```bash
docker compose up -d
docker compose --profile test build test   # 최초 1회 또는 requirements 변경 시
docker compose run --rm test               # 전체
docker compose run --rm test pytest -k core
```

- 픽스처: `client`(TestClient, 전역 `app`), `db_session`(테스트마다 트랜잭션 롤백). 세션 시작 시 `<DB_NAME>_test` DB를 새로 만든다.
- `pytest.ini`의 `filterwarnings = error` 때문에 DeprecationWarning도 실패로 처리된다. 경고를 낸 코드를 고친다(무시 규칙 추가는 B와 상의).
- 기능 테스트는 `tests/test_<기능>_*.py`. 테스트 전용 임시 라우트는 `/_t/...` 경로를 쓴다.

## 10. 린트

```bash
docker compose run --rm test ruff check .
```

- 설정은 `app/pyproject.toml`의 `[tool.ruff]`. 우선 D 파일(`app/app/core`, `config.py`, `main.py`, `tests/test_core.py`)을 0으로 맞추고, 다른 팀 코드는 D11에서 단계적으로 적용한다.

## 11. PR 규칙

- 다른 팀 소유 경로 수정 금지. 필요하면 해당 팀에 요청한다.
- `app/app/policy/matrix.yaml`, 차단 규칙 YAML, 사용자 안내 문구 변경은 D 리뷰 필수 + B16 재실행.
- `main.py` 라우터 등록, `config.py` 환경변수 추가는 `[D 리뷰 요청]` 커밋으로 요청한다.
