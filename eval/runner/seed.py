"""사전 조건(preconditions) 시드 — 앱 코드로 DB에 직접 만든다(만료 공유처럼 API로 만들 수 없는 상태 포함).

러너는 앱 이미지 안에서 DB에 접근할 수 있는 환경(staging Job·CI)에서 실행한다.
만드는 데이터는 모두 테스트 계정 소유라 is_test 트래픽과 같이 구분된다.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.db import SessionLocal
from app.features.resumes import service as resume_service
from app.features.share import service as share_service
from app.models import Share, Version
from app.retrieval.indexing import index_personal

LABEL = "평가 러너"
# C11-AUTHZ-05: 운영자가 조회할 사용자 자소서. 연락처는 저장 때 토큰화되어(B7) 인덱스에도 토큰으로 들어간다
USER_RESUME_BODY = "평가 러너 사용자 자소서. 고객 응대 경험을 정리했습니다. 연락처 010-2345-6789"
RETRIEVAL_SKIPPED = "retrieval(임베더 없음)"  # 결과 '미확인'에 남길 표시
POST_SHARE_BODY = "공유 이후 수정본"  # B19-SHARE-05 response_excludes와 같은 문장


class DbSeeder:
    def __init__(self, accounts, session_factory=SessionLocal, embedder=None):
        # embedder: 개인 인덱스 적재용(C3 index_personal). 없으면 자소서만 만들고 인덱싱은 건너뛴다(D bge-m3 대기)
        self.accounts, self.session_factory, self.embedder = accounts, session_factory, embedder
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
            if pre.get("target") == "user_resume":  # C11-05: 운영자가 검색으로 조회할 일반 사용자 자소서
                r, q = self._resume(db, owner, USER_RESUME_BODY)
                values["user_resume_id"] = str(r.id)
                if self.embedder is None:
                    values["_unverified"] = RETRIEVAL_SKIPPED
                else:
                    v = db.scalar(select(Version).where(Version.question_id == q.id))
                    # 저장본(토큰화된 본문)을 그대로 적재. source_id=자소서, chunk_index=문항 순서(guide 4.39)
                    index_personal(db, self.embedder, owner_id=owner, source_type="resume", source_id=r.id,
                                   text=v.body, chunk_index=q.position)
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
