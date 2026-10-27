"""B23 계정 삭제 검증 (part2_guide 4.55)."""
import uuid

import pytest

from app.config import get_settings
from app.db import SessionLocal
from app.features.deletion import service as deletion
from app.features.deletion import verify as v
from app.features.experiences import index_hooks as exp_index
from tests.test_deletion_b20 import FakeIdp


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(exp_index, "index_experience", lambda *a, **k: None)
    idp = FakeIdp()
    monkeypatch.setattr(deletion.admin_router, "get_cognito_client", lambda: idp)
    settings = get_settings().model_copy(update={"cognito_user_pool_id": "pool-test"})
    monkeypatch.setattr(deletion, "get_settings", lambda: settings)
    monkeypatch.setattr(v, "get_settings", lambda: settings)
    return idp


def test_scan_covers_every_user_reference():
    found = {f"{t.name}.{c.name}" for t, c, _ in v.user_columns()}
    for must in ("users.id", "resumes.owner_id", "versions.owner_id", "experiences.owner_id", "shares.owner_id",
                 "shares.shared_with", "share_comments.owner_id", "pii_vaults.owner_id", "user_keys.user_id",
                 "audit_logs.user_id", "download_tokens.owner_id", "user_profile_embeddings.owner_id",
                 "resumes.shared_with", "user_profile_embeddings.shared_with", "job_postings.owner_user_id",
                 "applications.owner_id", "writing_profiles.owner_id", "learning_roadmaps.owner_id"):
        assert must in found, must


def test_e2e_seeded_then_purged_leaves_nothing(fakes):
    before, after = v.run_e2e()
    assert not before.ok and before.rows["resumes.owner_id"] == 1 and before.s3_objects == 1
    assert before.rows["resumes.shared_with"] == 1  # 멘토로 공유받은 상대 자소서 복제본
    assert after.ok, v.render(after)
    assert after.rows["audit_logs.user_id"] == 0 and after.cognito == "absent"


def test_detects_leftovers():
    uid = f"left-{uuid.uuid4().hex[:8]}"
    with SessionLocal.begin() as db:
        deletion.request_account_deletion(db, uid)
    with SessionLocal() as db:
        r = v.verify(db, uid)
    assert not r.ok and r.rows["users.id"] == 1
    assert "✗ users.id: 1" in v.render(r)


def test_cli_exit_codes(fakes, capsys):
    assert v.main(["--e2e"]) == 0
    assert "통과(잔존 0건)" in capsys.readouterr().out
    uid = f"left-{uuid.uuid4().hex[:8]}"
    with SessionLocal.begin() as db:
        deletion.request_account_deletion(db, uid)
    assert v.main(["--user-id", uid]) == 1
