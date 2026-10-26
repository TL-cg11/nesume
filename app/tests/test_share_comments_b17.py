"""B17 멘토 문단별 코멘트 (part2_guide 4.47)."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.auth import Role
from app.db import SessionLocal
from app.features.share.comments import paragraphs
from app.models import PiiVault, Share, ShareComment
from tests.test_share_b10 import PII, As, _resume, _share, _sub
from tests.test_share_b10 import hook_calls, mentor, owner  # noqa: F401 (픽스처 공유)

BODY = f"첫 문단입니다.\n\n둘째 문단, 연락처 {PII}\n  \n셋째 문단"


def test_paragraph_split():
    assert paragraphs("a\n\nb\n \t\nc") == ["a", "b", "c"]
    assert paragraphs("한 문단\n줄바꿈만") == ["한 문단\n줄바꿈만"]
    assert paragraphs("\n\n  \n") == []
    assert paragraphs("a\r\n\r\nb") == ["a", "b"]


def _setup(owner, mentor):
    r = _resume(owner, bodies=(BODY,))
    s = _share(owner, r["id"], mentor.sub).json()
    view = mentor.get(f"/mentor/shares/{s['id']}").json()
    return r, s, view["questions"][0]


def test_mentor_view_has_paragraphs_readable(owner, mentor):
    _, _, q = _setup(owner, mentor)
    assert q["paragraphs"] == ["첫 문단입니다.", "둘째 문단, 연락처 (전화번호 비공개)", "셋째 문단"]
    assert q["comments"] == []


def test_comment_flow_owner_sees_original_mentor_sees_readable(owner, mentor):
    _, s, q = _setup(owner, mentor)
    base = f"/mentor/shares/{s['id']}/comments"
    res = mentor.post(base, json={"version_id": q["version_id"], "paragraph_index": 1,
                                  "body": "여기 연락처 010-9999-8888 은 빼는 게 좋겠어요"})
    assert res.status_code == 201, res.text
    c = res.json()
    assert c["body"] == "여기 연락처 (전화번호 비공개) 은 빼는 게 좋겠어요"
    with SessionLocal() as db:
        row = db.get(ShareComment, uuid.UUID(c["id"]))
        assert "010-9999-8888" not in row.body and row.vault_id and row.grade == "personal"
        assert db.get(PiiVault, row.vault_id).owner_id == owner.sub  # 대응표는 작성자 소유

    got = owner.get(f"/shares/{s['id']}/comments").json()
    assert got[0]["body"] == "여기 연락처 010-9999-8888 은 빼는 게 좋겠어요"
    assert got[0]["paragraph"] == f"둘째 문단, 연락처 {PII}" and got[0]["question_title"] == "문항0"
    assert got[0]["read_at"] is None
    lst = owner.get(f"/resumes/{s['resume_id']}/shares").json()[0]
    assert (lst["comment_count"], lst["unread_count"]) == (1, 1)

    assert owner.post(f"/shares/{s['id']}/comments/{c['id']}/read").json()["read_at"] is not None
    lst = owner.get(f"/resumes/{s['resume_id']}/shares").json()[0]
    assert lst["unread_count"] == 0
    assert mentor.get(f"/mentor/shares/{s['id']}").json()["questions"][0]["comments"][0]["id"] == c["id"]


def test_edit_and_delete_replace_vault(owner, mentor):
    _, s, q = _setup(owner, mentor)
    base = f"/mentor/shares/{s['id']}/comments"
    c = mentor.post(base, json={"version_id": q["version_id"], "paragraph_index": 0,
                                "body": "연락 010-1111-2222"}).json()
    with SessionLocal() as db:
        old_vault = db.get(ShareComment, uuid.UUID(c["id"])).vault_id
    e = mentor.patch(f"{base}/{c['id']}", json={"body": "고친 코멘트"})
    assert e.status_code == 200 and e.json()["body"] == "고친 코멘트"
    with SessionLocal() as db:
        assert db.get(PiiVault, old_vault) is None
        assert db.get(ShareComment, uuid.UUID(c["id"])).vault_id is None
    assert mentor.delete(f"{base}/{c['id']}").status_code == 204
    assert owner.get(f"/shares/{s['id']}/comments").json() == []


@pytest.mark.parametrize("payload_fix,status", [
    ({"paragraph_index": 3}, 422),              # 없는 문단
    ({"version_id": str(uuid.uuid4())}, 422),    # 공유에 고정되지 않은 버전
    ({"body": "   "}, 422),
    ({"body": "가" * 1001}, 422),
    ({"body": "주민번호 900101-1234567"}, 422),
    ({"grade": "public"}, 422),                  # 서버 전용 값
])
def test_comment_validation(owner, mentor, payload_fix, status):
    _, s, q = _setup(owner, mentor)
    payload = {"version_id": q["version_id"], "paragraph_index": 0, "body": "좋아요", **payload_fix}
    assert mentor.post(f"/mentor/shares/{s['id']}/comments", json=payload).status_code == status


def test_post_share_version_not_commentable(owner, mentor):
    r, s, q = _setup(owner, mentor)
    qid = owner.get(f"/resumes/{r['id']}").json()["questions"][0]["id"]
    v2 = owner.post(f"/resumes/{r['id']}/questions/{qid}/versions", json={"body": "v2 본문"}).json()
    res = mentor.post(f"/mentor/shares/{s['id']}/comments",
                      json={"version_id": v2["id"], "paragraph_index": 0, "body": "x"})
    assert res.status_code == 422


@pytest.mark.parametrize("end_it", ["expire", "revoke"])
def test_after_share_ends_mentor_blocked_owner_keeps(owner, mentor, end_it):
    _, s, q = _setup(owner, mentor)
    base = f"/mentor/shares/{s['id']}/comments"
    c = mentor.post(base, json={"version_id": q["version_id"], "paragraph_index": 0, "body": "코멘트"}).json()
    if end_it == "revoke":
        owner.delete(f"/shares/{s['id']}")
    else:
        now = datetime.now(UTC)
        with SessionLocal.begin() as db:
            db.execute(update(Share).where(Share.id == uuid.UUID(s["id"]))
                       .values(created_at=now - timedelta(days=2), expires_at=now - timedelta(seconds=1)))
    assert mentor.post(base, json={"version_id": q["version_id"], "paragraph_index": 0, "body": "x"}).status_code == 404
    assert mentor.patch(f"{base}/{c['id']}", json={"body": "y"}).status_code == 404
    assert mentor.delete(f"{base}/{c['id']}").status_code == 404
    assert [x["body"] for x in owner.get(f"/shares/{s['id']}/comments").json()] == ["코멘트"]


def test_isolation(owner, mentor):
    _, s, q = _setup(owner, mentor)
    c = mentor.post(f"/mentor/shares/{s['id']}/comments",
                    json={"version_id": q["version_id"], "paragraph_index": 0, "body": "코멘트"}).json()
    other_mentor = As(_sub("men"), Role.MENTOR)
    assert other_mentor.patch(f"/mentor/shares/{s['id']}/comments/{c['id']}", json={"body": "x"}).status_code == 404
    assert As(mentor.sub, Role.USER).post(f"/mentor/shares/{s['id']}/comments",
                                          json={"version_id": q["version_id"], "paragraph_index": 0,
                                                "body": "x"}).status_code == 403
    other_owner = As(_sub("own"))
    assert other_owner.get(f"/shares/{s['id']}/comments").status_code == 404
    assert other_owner.post(f"/shares/{s['id']}/comments/{c['id']}/read").status_code == 404


def test_comments_deleted_with_share(owner, mentor):
    _, s, q = _setup(owner, mentor)
    mentor.post(f"/mentor/shares/{s['id']}/comments",
                json={"version_id": q["version_id"], "paragraph_index": 0, "body": "코멘트"})
    with SessionLocal.begin() as db:
        db.execute(Share.__table__.delete().where(Share.id == uuid.UUID(s["id"])))
    with SessionLocal() as db:
        assert db.scalars(select(ShareComment).where(ShareComment.share_id == uuid.UUID(s["id"]))).all() == []
