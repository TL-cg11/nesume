"""사전 조건(preconditions) 시드 — 앱 코드로 DB에 직접 만든다(만료 공유처럼 API로 만들 수 없는 상태 포함).

러너는 앱 이미지 안에서 DB에 접근할 수 있는 환경(staging Job·CI)에서 실행한다.
만드는 데이터는 모두 테스트 계정 소유라 is_test 트래픽과 같이 구분된다.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.db import SessionLocal
from app.features.resumes import service as resume_service
from app.features.share import service as share_service
from app.models import Share

LABEL = "평가 러너"
POST_SHARE_BODY = "공유 이후 수정본"  # B19-SHARE-05 response_excludes와 같은 문장


class DbSeeder:
    def __init__(self, accounts, session_factory=SessionLocal):
        self.accounts, self.session_factory = accounts, session_factory
        self._base: dict | None = None  # 사전 조건이 없는 시나리오가 같이 쓰는 시드 자소서(자소서 50개 상한, 4.56)

    def _resume(self, db, owner: str, body: str = "평가 러너 시드 문단") -> tuple:
        resume_service.ensure_user(db, owner)
        r = resume_service.create_resume(db, owner, title="평가 러너 시드")
        q = resume_service.create_question(db, r, "시드 문항", None, 0)
        resume_service.create_version(db, owner, r.id, q.id, body, "manual")
        return r, q

    def prepare(self, s: dict) -> dict:
        pre = s.get("preconditions") or {}
        values: dict[str, str] = {"template_id": str(uuid.uuid4())}  # B9 전까지 없는 템플릿
        with self.session_factory.begin() as db:
            owner = self.accounts.sub("user")
            if "share_state" in pre:  # B19: 작성자(user) → 멘토(mentor) 공유
                mentor = self.accounts.sub("mentor")
                resume_service.ensure_user(db, mentor)
                r, q = self._resume(db, owner)
                sh = share_service.create_share(db, owner, r.id, mentor, None, mentor_label=LABEL, confirm=True)
                if pre["share_state"] == "revoked":
                    share_service.revoke_share(db, sh)
                elif pre["share_state"] == "expired":
                    now = datetime.now(UTC)
                    db.execute(update(Share).where(Share.id == sh.id)
                               .values(created_at=now - timedelta(days=2), expires_at=now - timedelta(seconds=1)))
                    share_service.sync_resume(db, r, now)
                if pre.get("edited_after_share"):
                    resume_service.create_version(db, owner, r.id, q.id, POST_SHARE_BODY, "manual")
                if pre.get("unshared_resume"):
                    rb, _ = self._resume(db, owner, "공유하지 않은 다른 자소서")
                    values["unshared_resume_id"] = str(rb.id)
                values.update(share_id=str(sh.id), resume_id=str(r.id), question_id=str(q.id))
            if pre.get("target") == "other_user_resume":  # C11: 다른 사용자(user2)의 자소서
                other = self.accounts.sub("user2")
                r2, _ = self._resume(db, other, "다른 사용자 자소서")
                values["other_resume_id"] = str(r2.id)
            if "resume_id" not in values:
                if self._base is None:
                    r, q = self._resume(db, owner)
                    self._base = {"resume_id": str(r.id), "question_id": str(q.id)}
                values.update(self._base)
        return values
