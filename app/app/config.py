from functools import lru_cache

from pydantic_settings import BaseSettings
from sqlalchemy import URL


class Settings(BaseSettings):
    """모든 연결 정보는 환경변수로만 주입한다. 기본값을 두지 않아 누락 시 기동 단계에서 실패한다."""

    # 미설정 시 안전한 쪽(문서 비노출 등)으로 동작하도록 기본값은 운영 기준
    app_env: str = "production"

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

    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None
    cognito_issuer: str | None = None
    cognito_jwks_url: str | None = None

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
