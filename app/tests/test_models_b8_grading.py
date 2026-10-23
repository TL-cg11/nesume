"""B8 저장 시 등급 자동 부여: 새 행은 등급표 값으로, 기존 행 등급 변경은 거부."""
import uuid

import pytest
from sqlalchemy import insert, select, update

from app.models import JobPosting, PiiVault, Resume, User
from app.models._common import Grade
from app.models.grading import GRADE_BY_MODEL, GradeChangeForbidden
from tests.test_models_b2 import EXPECTED_DEFAULT, _seed

WRONG = Grade.PUBLIC.value


def test_grade_table_matches_spec():
    by_table = {m.__tablename__: g for m, g in GRADE_BY_MODEL.items()}
    assert by_table == {**EXPECTED_DEFAULT, "pii_vaults": Grade.SENSITIVE}


@pytest.mark.parametrize("table", sorted(EXPECTED_DEFAULT))
def test_explicit_grade_on_insert_is_overridden(db_session, monkeypatch, table):
    # 코드가 생성 시 등급을 직접 넣어도 저장 시 등급표 값으로 바뀐다
    model = next(m for m in GRADE_BY_MODEL if m.__tablename__ == table)
    original = model.__init__

    def init(self, *a, **kw):
        original(self, *a, **kw)
        self.grade = WRONG

    monkeypatch.setattr(model, "__init__", init)
    obj = _seed(db_session)[table]
    pk = _pk(obj)
    db_session.expire_all()
    assert db_session.get(model, pk).grade == EXPECTED_DEFAULT[table]


def _pk(obj):
    return tuple(getattr(obj, c.key) for c in obj.__mapper__.primary_key)


@pytest.mark.parametrize("table", sorted(EXPECTED_DEFAULT))
def test_changing_grade_of_existing_row_rejected(db_session, table):
    obj = _seed(db_session)[table]
    obj.grade = WRONG
    with pytest.raises(GradeChangeForbidden):
        db_session.flush()


def test_other_updates_and_same_grade_allowed(db_session):
    r = _seed(db_session)["resumes"]
    r.title = "새 제목"
    r.grade = Grade.PERSONAL.value
    db_session.flush()


def test_bulk_statements_with_other_grade_rejected(db_session):
    r = _seed(db_session)["resumes"]
    with pytest.raises(GradeChangeForbidden):
        db_session.execute(update(Resume).where(Resume.id == r.id).values(grade=WRONG))
    with pytest.raises(GradeChangeForbidden):
        db_session.execute(insert(Resume).values(owner_id=r.owner_id, title="t", grade=WRONG))
    with pytest.raises(GradeChangeForbidden):
        db_session.execute(insert(Resume), [{"owner_id": r.owner_id, "title": "t", "grade": WRONG}])


def test_bulk_statements_without_grade_allowed(db_session):
    r = _seed(db_session)["resumes"]
    db_session.execute(update(Resume).where(Resume.id == r.id).values(title="일괄"))
    db_session.execute(insert(Resume).values(owner_id=r.owner_id, title="t2"))
    grades = db_session.scalars(select(Resume.grade).where(Resume.owner_id == r.owner_id)).all()
    assert set(grades) == {Grade.PERSONAL.value}


def test_pii_vault_grade_assigned(db_session):
    u = User(id=f"b8-{uuid.uuid4()}")
    db_session.add(u)
    db_session.flush()
    v = PiiVault(id=uuid.uuid4().hex, owner_id=u.id, entries_enc=b"x", format_version=1, grade=WRONG)
    db_session.add(v)
    db_session.flush()
    assert v.grade == Grade.SENSITIVE.value


def test_c_tables_not_enforced(db_session):
    # C 소유 테이블은 B8 대상 아님(C에 제안만, part2_guide 4.36)
    p = JobPosting(source="seoul", link_key=uuid.uuid4().hex * 2, content_hash=uuid.uuid4().hex * 2,
                   title="t", grade=Grade.INTERNAL.value)
    db_session.add(p)
    db_session.flush()
    assert p.grade == Grade.INTERNAL.value
