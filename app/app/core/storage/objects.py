"""S3 비공개 저장 (B6, spec 3.2).

- 버킷은 퍼블릭 차단 + KMS 기본 암호화(init/localstack, AWS는 Terraform D8).
- 객체 키는 `users/{user_id}/...` 형식만 허용하고, 키에 이름 등 PII를 넣지 않는다.
- S3 클라이언트는 공용 `app.aws.client`를 사용한다(endpoint는 환경변수).
"""
import re
from collections.abc import Iterator

from botocore.exceptions import ClientError

from app import aws
from app.config import get_settings

# 키 구성 요소: 영숫자와 . _ - 만 허용(경로 조작·PII 혼입 방지)
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CHUNK_SIZE = 64 * 1024


class ObjectNotFound(Exception):
    pass


def user_object_key(user_id: str, *parts: str) -> str:
    """`users/{user_id}/{parts...}` 키를 만든다. 구성 요소는 안전한 문자만 허용."""
    segments = (user_id, *parts)
    if not parts or any(not _SEGMENT.match(p) or ".." in p for p in segments):
        raise ValueError("invalid object key segment")
    return "/".join(("users", *segments))


def _bucket() -> str:
    bucket = get_settings().s3_bucket_name
    if not bucket:
        raise RuntimeError("S3_BUCKET_NAME is not configured")
    return bucket


def put_object(key: str, data: bytes, content_type: str) -> None:
    s = get_settings()
    extra = {"ServerSideEncryption": "aws:kms"}
    if s.kms_key_alias:
        extra["SSEKMSKeyId"] = s.kms_key_alias
    aws.client("s3").put_object(Bucket=_bucket(), Key=key, Body=data, ContentType=content_type, **extra)


def open_object(key: str) -> Iterator[bytes]:
    """객체 본문을 청크 단위로 읽는다. 없으면 ObjectNotFound."""
    try:
        body = aws.client("s3").get_object(Bucket=_bucket(), Key=key)["Body"]
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            raise ObjectNotFound(key) from None
        raise
    return body.iter_chunks(CHUNK_SIZE)


def delete_object(key: str) -> None:
    aws.client("s3").delete_object(Bucket=_bucket(), Key=key)


def delete_user_objects(user_id: str) -> int:
    """`users/{user_id}/` 아래 객체를 모두 지운다(계정 삭제, B20). 지운 개수. 다시 불러도 안전하다."""
    if not _SEGMENT.match(user_id) or ".." in user_id:
        raise ValueError("invalid object key segment")
    s3 = aws.client("s3")
    deleted = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=_bucket(), Prefix=f"users/{user_id}/"):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:  # 한 번에 최대 1,000개(S3 제한), 페이지가 1,000개 단위라 그대로 보낸다
            s3.delete_objects(Bucket=_bucket(), Delete={"Objects": keys, "Quiet": True})
            deleted += len(keys)
    return deleted
