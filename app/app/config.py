from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings
from sqlalchemy import URL


class Settings(BaseSettings):
    """모든 연결 정보는 환경변수로만 주입한다. 기본값을 두지 않아 누락 시 기동 단계에서 실패한다."""

    # 미설정 시 안전한 쪽(문서 비노출 등)으로 동작하도록 기본값은 운영 기준.
    # Literal이라 APP_ENV=prod 같은 오타는 기동 시 바로 실패한다.
    app_env: Literal["local", "test", "dev", "staging", "production"] = "production"
    # 이미지 빌드 시 git sha를 넣는다(D4). /health가 돌려주므로 배포 확인에 쓴다.
    app_version: str = "dev"

    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    # 역할 × 등급 매트릭스(D2). C2 로더가 읽는다.
    # 위치는 C가 둔 app/app/policy/matrix.yaml 유지(merge-review 3-2).
    # 컨테이너 작업 디렉터리 /srv 기준 경로(/srv/app/policy/matrix.yaml).
    policy_matrix_path: str = "app/policy/matrix.yaml"

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    aws_region: str | None = None
    # 로컬은 LocalStack 주소, AWS에서는 미설정(None)으로 두면 기본 엔드포인트를 사용한다.
    aws_endpoint_url: str | None = None
    s3_bucket_name: str | None = None
    kms_key_alias: str | None = None
    app_secret_name: str | None = None

    # A2 LLM 제공자. none 이면 호출 시 LlmUnavailable → 기능들이 규칙 결과만 돌려준다(테스트 기본).
    llm_provider: Literal["none", "bedrock"] = "none"
    # Converse API 라 모델 교체는 이 값 하나. 10-28 현재 Anthropic 은 계정 게이트로 거부 →
    # 임시 Nova 2 Lite. 열리면 global.anthropic.claude-haiku-5-5 (IAM 은 둘 다 허용).
    llm_model_id: str = "global.amazon.nova-2-lite-v1:0"
    bedrock_region: str = "ap-northeast-2"
    # 로컬 전용. compose 의 AWS_* 는 LocalStack 더미 키라 Bedrock 에 못 쓴다.
    # AWS(EKS)에서는 비워 두고 IRSA(기본 자격증명 체인)를 쓴다.
    bedrock_access_key_id: str | None = None
    bedrock_secret_access_key: str | None = None
    bedrock_session_token: str | None = None

    # D20/C3 임베딩 서비스(TEI + bge-m3). 비우면 임베딩 없음 → C6 리트리버 미주입·추천 빈 결과.
    # 운영은 Helm ConfigMap 이 채운다(클러스터 내부 http://<release>-embedder:8080).
    embedding_url: str = ""
    # 차원 1024 와 짝(app/models/embedding.py MODEL_VERSION). 값 확인용 — 바꾸면 재임베딩 필요.
    embedding_model: str = "bge-m3"

    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None
    # D6/D7: 앱 클라이언트가 web·runner 둘이라 복수 허용(쉼표 구분). 비어 있으면 cognito_client_id 하나.
    cognito_client_ids: str = ""
    cognito_issuer: str | None = None
    cognito_jwks_url: str | None = None
    # 로컬(cognito-local) 전용 엔드포인트. AWS 에서는 미설정. 시드·admin API 의 cognito-idp 호출에만 쓴다.
    cognito_local_endpoint: str | None = None
    # D7: 운영자 보호 API 는 TOTP 등록 + 최근 N분 내 로그인(auth_time)을 요구한다.
    operator_mfa_required: bool = True
    mfa_session_minutes: int = 15
    # test 그룹 운영자(시드 test-operator1)는 MFA 면제. dev·staging 만 true, production 은 무시된다.
    mfa_exempt_test_operators: bool = False

    @property
    def cognito_client_id_set(self) -> frozenset[str]:
        ids = {c.strip() for c in self.cognito_client_ids.split(",") if c.strip()}
        if not ids and self.cognito_client_id:
            ids = {self.cognito_client_id}
        return frozenset(ids)

    @property
    def is_local(self) -> bool:
        return self.app_env in ("local", "test")

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
