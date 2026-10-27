"""계정 삭제 검증 (tasks B23, spec 10.2, part2_guide 4.55).

삭제가 끝난 계정에 대해 "잔존 0건"을 확인한다.
- DB: 모든 테이블에서 사용자 ID가 들어가는 컬럼을 **자동으로** 찾아 센다(users FK, 이름이 owner_id·user_id·
  owner_user_id·shared_with인 컬럼, JSON 목록 안의 user_id). 다른 팀이 테이블을 추가해도 빠지지 않는다
- 감사 로그: 원래 ID로 된 행이 0이어야 한다(익명 ID로 치환·보존)
- 데이터 키(user_keys), S3 `users/{id}/`, Cognito 계정이 없어야 한다
- 의도된 예외: templates.created_by(운영자 이력 보존, B1 설계)

실행:
  python -m app.features.deletion.verify --user-id <id> [--user-id ...]   지정 계정 검사
  python -m app.features.deletion.verify --e2e                             임시 계정으로 전체 흐름(채우기→삭제→검사)
하나라도 남으면 종료 코드 1.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from botocore.exceptions import ClientError
from sqlalchemy import String, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app import aws
from app.auth import admin_router
from app.config import get_settings
from app.core.errors import NotFoundError
from app.db import Base, SessionLocal

USER_COLUMN_NAMES = {"owner_id", "user_id", "owner_user_id", "shared_with"}
# (테이블, 컬럼): 사유 — 계정 삭제 뒤에도 남는 것이 정상인 곳
ALLOWED = {("templates", "created_by"): "운영자 작성 이력 보존(B1 설계, FK 없음)"}


@dataclass
class Report:
    user_id: str
    rows: dict[str, int] = field(default_factory=dict)  # "테이블.컬럼" → 잔존 수(0만 통과)
    s3_objects: int = 0
    cognito: str = "skipped"  # absent / present / skipped
    allowed: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(self.rows.values()) and self.s3_objects == 0 and self.cognito != "present"


def user_columns():
    """(table, column, kind) 목록. kind: 'eq'(문자열 비교) / 'json'(JSON 목록의 user_id)."""
    out = []
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            fk_users = any(fk.column.table.name == "users" for fk in col.foreign_keys)
            if table.name == "users" and col.name == "id":
                out.append((table, col, "eq"))
            elif isinstance(col.type, JSONB) and col.name == "shared_with":
                out.append((table, col, "json"))
            elif isinstance(col.type, String) and (fk_users or col.name in USER_COLUMN_NAMES):
                out.append((table, col, "eq"))
    return out


def _count(db: Session, table, col, kind: str, user_id: str) -> int:
    if kind == "json":
        cond = col.op("@>")(func.jsonb_build_array(func.jsonb_build_object("user_id", user_id)))
    else:
        cond = col == user_id
    return db.scalar(select(func.count()).select_from(table).where(cond)) or 0


def _s3_count(user_id: str) -> int:
    bucket = get_settings().s3_bucket_name
    res = aws.client("s3").list_objects_v2(Bucket=bucket, Prefix=f"users/{user_id}/", MaxKeys=1)
    return res.get("KeyCount", 0)


def _cognito_state(user_id: str) -> str:
    pool_id = get_settings().cognito_user_pool_id
    if not pool_id:
        return "skipped"
    idp = admin_router.get_cognito_client()
    try:
        admin_router._resolve_username(idp, pool_id, user_id)
        return "present"
    except NotFoundError:
        return "absent"
    except ClientError as e:
        if admin_router._code(e) == "UserNotFoundException":
            return "absent"
        raise


def verify(db: Session, user_id: str, *, check_cognito: bool = True) -> Report:
    r = Report(user_id=user_id)
    for table, col, kind in user_columns():
        key = f"{table.name}.{col.name}"
        n = _count(db, table, col, kind, user_id)
        if (table.name, col.name) in ALLOWED:
            r.allowed[key] = n
        else:
            r.rows[key] = n
    r.s3_objects = _s3_count(user_id)
    if check_cognito:
        r.cognito = _cognito_state(user_id)
    return r


def render(r: Report) -> str:
    lines = [f"계정 {r.user_id} — {'통과(잔존 0건)' if r.ok else '실패(잔존 있음)'}"]
    for key, n in sorted(r.rows.items()):
        lines.append(f"  {'✗' if n else '✓'} {key}: {n}")
    for key, n in sorted(r.allowed.items()):
        lines.append(f"  - {key}: {n} (예외: {ALLOWED[tuple(key.split('.'))]})")
    lines.append(f"  {'✗' if r.s3_objects else '✓'} s3 users/{r.user_id}/: {r.s3_objects}")
    lines.append(f"  {'✗' if r.cognito == 'present' else '✓'} cognito: {r.cognito}")
    return "\n".join(lines)


# --- 처음부터 끝까지(e2e) -----------------------------------------------------

def seed_everything(db: Session, user_id: str, other_id: str) -> None:
    """임시 계정에 지울 대상을 종류별로 하나씩 만든다(다른 계정과의 공유 양방향 포함)."""
    from app.core.storage import objects, tokens
    from app.features.experiences import service as exp_service
    from app.features.resumes import service as resume_service
    from app.features.share import comments as share_comments
    from app.features.share import service as share_service
    from app.models import AuditLog, UserProfileEmbedding
    from app.models.embedding import EMBED_DIM

    for uid in (user_id, other_id):
        resume_service.ensure_user(db, uid)
    vec = [1.0] + [0.0] * (EMBED_DIM - 1)
    r = resume_service.create_resume(db, user_id, title="검증용 자소서")
    q = resume_service.create_question(db, r, "문항", None, 0)
    v, _ = resume_service.create_version(db, user_id, r.id, q.id, "연락처 010-1234-5678", "manual")
    e = exp_service.create_experience(db, user_id, {"title": "검증용 경험 hong@example.com", "type": "project"})
    for kind, sid in (("resume", r.id), ("experience", e.id)):
        db.add(UserProfileEmbedding(owner_id=user_id, source_type=kind, source_id=sid, content="x", embedding=vec))
    s = share_service.create_share(db, user_id, r.id, other_id, None, mentor_label="검증")  # 작성자로서 공유
    share_comments.add(db, s, v.id, 0, "검증 코멘트")
    r2 = resume_service.create_resume(db, other_id, title="상대 자소서")  # 멘토로서 공유받음
    q2 = resume_service.create_question(db, r2, "문항", None, 0)
    resume_service.create_version(db, other_id, r2.id, q2.id, "본문", "manual")
    share_service.create_share(db, other_id, r2.id, user_id, None, mentor_label="검증")
    db.add(AuditLog(request_id=uuid.uuid4(), session_id="s", user_id=user_id, role="user", feature="verify",
                    decision="allow"))
    key = objects.user_object_key(user_id, "verify", "a.txt")
    objects.put_object(key, b"x", "text/plain")
    tokens.issue(db, user_id, key, "a.txt", "text/plain")
    db.flush()


def run_e2e() -> list[Report]:
    from app.features.deletion import service as deletion

    user_id, other_id = f"verify-{uuid.uuid4().hex[:12]}", f"verify-{uuid.uuid4().hex[:12]}"
    with SessionLocal.begin() as db:
        seed_everything(db, user_id, other_id)
        deletion.request_account_deletion(db, user_id, now=datetime.now(UTC) - deletion.GRACE - timedelta(seconds=1))
    with SessionLocal() as db:
        before = verify(db, user_id, check_cognito=False)
    with SessionLocal.begin() as db:  # 이 계정만 삭제(다른 예약 계정은 건드리지 않음)
        deletion.purge_account(db, user_id)
    with SessionLocal() as db:
        after = verify(db, user_id)
        other_left = db.scalar(text("SELECT count(*) FROM resumes WHERE owner_id = :u"), {"u": other_id})
    with SessionLocal.begin() as db:  # 상대 계정 정리(검증 데이터)
        db.execute(text("DELETE FROM users WHERE id = :u"), {"u": other_id})
    if not other_left:
        after.rows["(상대 계정 자소서 보존)"] = 1  # 다른 사용자 데이터가 같이 지워지면 실패
    return [before, after]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="B23 계정 삭제 검증")
    p.add_argument("--user-id", action="append", default=[])
    p.add_argument("--e2e", action="store_true", help="임시 계정으로 채우기→삭제→검사")
    p.add_argument("--json-out", help="e2e 결과를 JSON으로 저장(B22 리포트 입력)")
    a = p.parse_args(argv)
    if a.e2e:
        before, after = run_e2e()
        print("[삭제 전]\n" + render(before) + "\n\n[삭제 후]\n" + render(after))
        if a.json_out:
            import json
            from dataclasses import asdict

            data = {"measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "before": {**asdict(before), "ok": before.ok}, "after": {**asdict(after), "ok": after.ok}}
            with open(a.json_out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        return 0 if after.ok and not before.ok else 1
    if not a.user_id:
        p.error("--user-id 또는 --e2e")
    results = []
    with SessionLocal() as db:
        for uid in a.user_id:
            results.append(verify(db, uid))
    print("\n\n".join(render(r) for r in results))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
