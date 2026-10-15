"""B1 핵심 데이터 모델 v0 검증."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db import engine
from app.models import (
    Application,
    AuditLog,
    Experience,
    PromptTemplate,
    Question,
    Resume,
    Share,
    User,
    Version,
)

ALEMBIC = Config("/srv/alembic.ini")
# tasks.md B1 목록
B1_TABLES = {
    "users", "resumes", "questions", "versions",
    "experiences", "templates", "shares", "applications", "audit_logs",
}


def _user(session, sub=None):
    u = User(id=sub or str(uuid.uuid4()))
    session.add(u)
    session.flush()
    return u


def _resume_with_versions(session, owner, n_versions=2):
    r = Resume(owner_id=owner.id, title="네이버 백엔드")
    q = Question(resume=r, owner_id=owner.id, title="지원 동기", char_limit=800)
    session.add_all([r, q])
    session.flush()
    versions = [
        Version(question_id=q.id, owner_id=owner.id, version_no=i + 1, body=f"본문 {i}",
                char_count=4, source="manual")
        for i in range(n_versions)
    ]
    session.add_all(versions)
    session.flush()
    return r, q, versions


# --- 스키마 ----------------------------------------------------------------

def test_all_b1_tables_exist():
    assert B1_TABLES <= set(inspect(engine).get_table_names())


def test_models_match_migrations():
    # 모델과 마이그레이션이 어긋나면 실패한다(마이그레이션 누락 방지)
    command.check(ALEMBIC)


def test_migration_downgrade_and_upgrade_roundtrip():
    command.downgrade(ALEMBIC, "0001")
    try:
        assert not (B1_TABLES & set(inspect(engine).get_table_names()))
    finally:
        command.upgrade(ALEMBIC, "head")
    assert B1_TABLES <= set(inspect(engine).get_table_names())


# --- 버전 불변·스냅샷 ------------------------------------------------------

def test_versions_are_immutable(db_session):
    u = _user(db_session)
    _, _, (v1, _) = _resume_with_versions(db_session, u)
    with pytest.raises(DBAPIError, match="immutable"):
        db_session.execute(update(Version).where(Version.id == v1.id).values(body="덮어쓰기"))
        db_session.flush()


def test_version_number_unique_per_question(db_session):
    u = _user(db_session)
    _, q, _ = _resume_with_versions(db_session, u)
    db_session.add(Version(question_id=q.id, owner_id=u.id, version_no=1, body="x",
                           char_count=1, source="manual"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_application_pins_question_versions(db_session):
    # spec 4.5: 지원 시점의 버전을 고정 참조(문항별 버전 ID 배열)
    u = _user(db_session)
    r, _, (v1, v2) = _resume_with_versions(db_session, u)
    a = Application(owner_id=u.id, resume_id=r.id, version_ids=[v1.id], status="applied")
    db_session.add(a)
    db_session.flush()
    db_session.refresh(a)
    assert a.version_ids == [v1.id]


def test_deleting_resume_keeps_application(db_session):
    u = _user(db_session)
    r, _, (v1, _) = _resume_with_versions(db_session, u)
    pinned = v1.id
    app_ = Application(owner_id=u.id, resume_id=r.id, version_ids=[pinned], status="applied")
    db_session.add(app_)
    db_session.flush()

    db_session.execute(delete(Resume).where(Resume.id == r.id))
    db_session.flush()
    db_session.expire_all()
    remaining = db_session.get(Application, app_.id)
    assert remaining.resume_id is None
    # 배열은 FK가 없어 값이 남는다. 참조 버전 보호·정리는 B4·B20 서비스 로직
    assert remaining.version_ids == [pinned]


def test_status_and_type_are_unconstrained_until_team_decides(db_session):
    # 문서에 값 목록이 없는 컬럼은 CHECK 제약 없이 둔다
    u = _user(db_session)
    db_session.add(Resume(owner_id=u.id, title="t", status="anything"))
    db_session.add(Experience(owner_id=u.id, title="t", type="hobby"))
    db_session.flush()


# --- 사용자 삭제 연쇄 (B20 물리 삭제 기반) ---------------------------------

def test_deleting_user_removes_all_owned_rows(db_session):
    u = _user(db_session)
    r, _, _ = _resume_with_versions(db_session, u)
    db_session.add(Experience(owner_id=u.id, title="동아리 프로젝트", type="project"))
    db_session.add(Application(owner_id=u.id, status="applied"))
    db_session.flush()

    db_session.execute(delete(User).where(User.id == u.id))
    db_session.flush()
    for model in (Resume, Question, Version, Experience, Application):
        assert db_session.scalar(select(model).where(model.owner_id == u.id)) is None


def test_audit_logs_survive_user_deletion(db_session):
    # spec 10.2: 감사 로그는 계정 삭제 후에도 보존(user_id는 B20에서 anon_id로 치환)
    u = _user(db_session)
    rid = uuid.uuid4()
    db_session.add(AuditLog(request_id=rid, session_id="s1", user_id=u.id, role="user",
                            feature="rewrite", decision="allow"))
    db_session.flush()
    db_session.execute(delete(User).where(User.id == u.id))
    db_session.flush()
    assert db_session.get(AuditLog, rid) is not None


# --- 값 제약 ---------------------------------------------------------------

@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(lambda uid: Application(owner_id=uid, status="pending"), id="application-status"),
        pytest.param(lambda uid: AuditLog(request_id=uuid.uuid4(), session_id="s", user_id=uid,
                                          role="admin", feature="x", decision="allow"), id="audit-role"),
        pytest.param(lambda uid: AuditLog(request_id=uuid.uuid4(), session_id="s", user_id=uid,
                                          role="user", feature="x", decision="flag"), id="audit-decision-flag"),
    ],
)
def test_check_constraints_reject_unknown_values(db_session, factory):
    u = _user(db_session)
    db_session.add(factory(u.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_only_one_active_template_per_name(db_session):
    db_session.add(PromptTemplate(name="rewrite", purpose="rewrite", body="v1", version=1,
                                  is_active=True, created_by="op"))
    db_session.add(PromptTemplate(name="rewrite", purpose="rewrite", body="v2", version=2,
                                  is_active=False, created_by="op"))
    db_session.flush()
    db_session.add(PromptTemplate(name="rewrite", purpose="rewrite", body="v3", version=3,
                                  is_active=True, created_by="op"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_share_constraints(db_session):
    owner, mentor = _user(db_session), _user(db_session)
    r, _, _ = _resume_with_versions(db_session, owner, 1)
    now = datetime.now(UTC)
    db_session.add(Share(resume_id=r.id, owner_id=owner.id, shared_with=mentor.id,
                         expires_at=now + timedelta(days=7)))
    db_session.flush()

    db_session.add(Share(resume_id=r.id, owner_id=owner.id, shared_with=owner.id,
                         expires_at=now + timedelta(days=7)))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_uuid_primary_keys_generated_server_side(db_session):
    u = _user(db_session)
    rid = db_session.execute(
        text("INSERT INTO resumes (owner_id, title) VALUES (:o, 't') RETURNING id"), {"o": u.id}
    ).scalar()
    assert isinstance(rid, uuid.UUID)
