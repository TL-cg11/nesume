import boto3
from botocore.config import Config

from app.config import get_settings


def client(service: str):
    """AWS SDK 클라이언트. endpoint는 환경변수(AWS_ENDPOINT_URL)로만 결정한다."""
    s = get_settings()
    return boto3.client(
        service,
        region_name=s.aws_region,
        endpoint_url=s.aws_endpoint_url,
        config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 2}),
    )
