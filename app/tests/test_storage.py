"""B6 S3 비공개 저장 + 앱 경유 1회용 다운로드."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import aws
from app.auth import CurrentUser, get_current_user
from app.config import get_settings
from app.core.storage import objects, tokens
from app.db import SessionLocal
from app.features.resumes.service import ensure_user
from app.main import app
from app.models import DownloadToken


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _as(sub: str) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub=sub)
    return TestClient(app)


@pytest.fixture
def owner():
    sub = f"owner-{uuid.uuid4()}"
    with SessionLocal() as db:
        ensure_user(db, sub)
        db.commit()
    return sub


@pytest.fixture
def stored(owner):
    key = objects.user_object_key(owner, "resumes", str(uuid.uuid4()), "doc.pdf")
    objects.put_object(key, b"%PDF-1.7 test", "application/pdf")
    yield key
    objects.delete_object(key)


def _issue(owner, key, filename="홍길동_네이버.pdf", now=None):
    with SessionLocal() as db:
        token, exp = tokens.issue(db, owner, key, filename, "application/pdf", now=now)
        db.commit()
    return token, exp


# --- 객체 키 ----------------------------------------------------------------

@pytest.mark.parametrize("parts", [("..", "x"), ("a/b",), ("",), ("이름.pdf",), (".hidden",)])
def test_object_key_rejects_unsafe_segments(parts):
    with pytest.raises(ValueError):
        objects.user_object_key("user-1", *parts)


def test_object_key_format():
    assert objects.user_object_key("u1", "resumes", "r1", "v1.pdf") == "users/u1/resumes/r1/v1.pdf"


# --- 저장 -------------------------------------------------------------------

def test_put_object_is_kms_encrypted(stored):
    head = aws.client("s3").head_object(Bucket=get_settings().s3_bucket_name, Key=stored)
    assert head["ServerSideEncryption"] == "aws:kms"


# --- 다운로드 ---------------------------------------------------------------

def test_download_once_with_headers(owner, stored):
    token, exp = _issue(owner, stored)
    assert exp - datetime.now(UTC) <= tokens.TOKEN_TTL

    c = _as(owner)
    r = c.get(f"/downloads/{token}")
    assert r.status_code == 200
    assert r.content == b"%PDF-1.7 test"
    assert r.headers["content-type"] == "application/pdf"
    assert "filename*=UTF-8''%ED%99%8D" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"
    # 1회용
    assert c.get(f"/downloads/{token}").status_code == 404


def test_other_user_cannot_use_and_does_not_consume(owner, stored):
    token, _ = _issue(owner, stored)
    assert _as(f"intruder-{uuid.uuid4()}").get(f"/downloads/{token}").status_code == 404
    assert _as(owner).get(f"/downloads/{token}").status_code == 200


def test_expired_token_rejected(owner, stored):
    token, _ = _issue(owner, stored, now=datetime.now(UTC) - timedelta(minutes=11))
    assert _as(owner).get(f"/downloads/{token}").status_code == 404


def test_reissue_revokes_previous_token(owner, stored):
    old, _ = _issue(owner, stored)
    new, _ = _issue(owner, stored)
    c = _as(owner)
    assert c.get(f"/downloads/{old}").status_code == 404
    assert c.get(f"/downloads/{new}").status_code == 200


def test_reissue_for_other_object_keeps_token(owner, stored):
    other = objects.user_object_key(owner, "resumes", str(uuid.uuid4()), "other.pdf")
    first, _ = _issue(owner, stored)
    _issue(owner, other)
    assert _as(owner).get(f"/downloads/{first}").status_code == 200


def test_unknown_token_and_missing_object(owner):
    c = _as(owner)
    assert c.get("/downloads/not-a-token").status_code == 404
    missing = objects.user_object_key(owner, "resumes", "gone", "x.pdf")
    token, _ = _issue(owner, missing)
    assert c.get(f"/downloads/{token}").status_code == 404


def test_requires_authentication(owner, stored):
    token, _ = _issue(owner, stored)
    assert TestClient(app).get(f"/downloads/{token}").status_code == 401


def test_raw_token_not_stored(owner, stored):
    token, _ = _issue(owner, stored)
    with SessionLocal() as db:
        hashes = db.scalars(select(DownloadToken.token_hash).where(DownloadToken.owner_id == owner)).all()
    assert token not in hashes and all(len(h) == 64 for h in hashes)


def test_concurrent_redeem_only_once(owner, stored):
    token, _ = _issue(owner, stored)
    with SessionLocal() as a, SessionLocal() as b:
        first = tokens.redeem(a, owner, token)
        a.commit()
        second = tokens.redeem(b, owner, token)
        b.commit()
    assert first is not None and second is None


# --- 정리 배치 --------------------------------------------------------------

def test_cleanup_removes_only_tokens_expired_over_24h_in_batches(owner):
    now = datetime.now(UTC)
    key = objects.user_object_key(owner, "cleanup", "x.pdf")
    with SessionLocal() as db:
        for i in range(5):  # 만료 후 25시간 이상
            db.add(DownloadToken(token_hash=uuid.uuid4().hex * 2, owner_id=owner, object_key=key,
                                 filename="f", content_type="application/pdf",
                                 expires_at=now - timedelta(hours=25 + i)))
        db.add(DownloadToken(token_hash=uuid.uuid4().hex * 2, owner_id=owner, object_key=key,
                             filename="f", content_type="application/pdf",
                             expires_at=now - timedelta(hours=23)))  # 24시간 미만: 유지
        db.commit()

        assert tokens.cleanup(db, now=now, batch=3) == 3   # 1회 최대 batch개
        assert tokens.cleanup(db, now=now, batch=3) == 2
        assert tokens.cleanup(db, now=now, batch=3) == 0
        db.commit()
        remaining = db.scalar(select(func.count()).where(DownloadToken.object_key == key))
    assert remaining == 1


def test_cleanup_deletes_oldest_first(owner):
    now = datetime.now(UTC)
    key = objects.user_object_key(owner, "cleanup-order", "x.pdf")
    with SessionLocal() as db:
        ages = [30, 48, 26]
        for h in ages:
            db.add(DownloadToken(token_hash=uuid.uuid4().hex * 2, owner_id=owner, object_key=key,
                                 filename=str(h), content_type="application/pdf",
                                 expires_at=now - timedelta(hours=h)))
        db.commit()
        tokens.cleanup(db, now=now, batch=1)
        db.commit()
        left = sorted(db.scalars(select(DownloadToken.filename).where(DownloadToken.object_key == key)).all())
    assert left == ["26", "30"]
