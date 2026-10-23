"""저장 시 등급 자동 부여 (tasks B8, spec 6.4, part2_guide 4.36).

테이블별 등급은 기능으로 정해지며 바뀌지 않는다. ORM 저장 경로 전부에 적용해 B 서비스뿐 아니라
같은 테이블에 쓰는 다른 팀 코드(C15 지원 기록, A8 감사 로그 등)도 같은 규칙을 따른다.

- 새 행: 넘어온 값과 관계없이 등급표의 값으로 덮어쓴다(자동 부여)
- 기존 행의 등급 변경: GradeChangeForbidden
- 일괄 INSERT·UPDATE 문(session.execute)에 등급표와 다른 값: GradeChangeForbidden

ORM을 거치지 않는 SQL은 DB 기본값(server_default)과 CHECK(5등급)까지만 보장된다.
대상은 tasks B8에 나열된 테이블. 말투 프로필(A14)은 모델 취합 후, 면접 연습은 B13에서 추가한다.
"""
from sqlalchemy import event, inspect
from sqlalchemy.orm import ORMExecuteState, Session

from app.models._common import Grade
from app.models.application import Application
from app.models.audit import AuditLog
from app.models.experience import Experience
from app.models.pii import PiiVault
from app.models.resume import Question, Resume, Version
from app.models.template import PromptTemplate

# spec 6.4 기능별 등급
GRADE_BY_MODEL: dict[type, Grade] = {
    Resume: Grade.PERSONAL,
    Question: Grade.PERSONAL,
    Version: Grade.PERSONAL,
    Experience: Grade.PERSONAL,
    Application: Grade.PERSONAL,
    PromptTemplate: Grade.INTERNAL,
    PiiVault: Grade.SENSITIVE,   # PII 토큰화 전 원문
    AuditLog: Grade.SENSITIVE,
}


class GradeChangeForbidden(ValueError):
    """등급은 기능별로 고정이라 코드에서 바꿀 수 없다."""


def _assign(mapper, connection, target) -> None:
    target.grade = GRADE_BY_MODEL[mapper.class_].value


def _forbid_change(mapper, connection, target) -> None:
    history = inspect(target).attrs.grade.history
    if history.has_changes() and target.grade != GRADE_BY_MODEL[mapper.class_].value:
        raise GradeChangeForbidden(f"{mapper.class_.__tablename__}.grade 변경 불가")


for _model in GRADE_BY_MODEL:
    event.listen(_model, "before_insert", _assign)
    event.listen(_model, "before_update", _forbid_change)


def _grades_in(mapping, out: list) -> None:
    for key, value in mapping.items():
        if getattr(key, "key", key) == "grade":
            out.append(getattr(value, "value", value))  # BindParameter면 실제 값


def _statement_grades(state: ORMExecuteState) -> list:
    """일괄 문장에 직접 지정된 grade 값들.

    VALUES 절·다중 VALUES·ON CONFLICT DO UPDATE SET·실행 파라미터를 본다. SQLAlchemy 문장 객체의
    내부 속성(_values 등)을 읽으므로 SQLAlchemy 버전 변경 시 tests/test_models_b8_grading.py로 확인한다.
    """
    stmt = state.statement
    out: list = []
    _grades_in(getattr(stmt, "_values", None) or {}, out)
    for rows in getattr(stmt, "_multi_values", ()) or ():
        for row in rows:
            if isinstance(row, dict):
                _grades_in(row, out)
    conflict = getattr(stmt, "_post_values_clause", None)
    _grades_in(dict(getattr(conflict, "update_values_to_set", None) or []), out)
    params = state.parameters
    for row in params if isinstance(params, list) else [params or {}]:
        _grades_in(row, out)
    return out


@event.listens_for(Session, "do_orm_execute")
def _guard_bulk(state: ORMExecuteState) -> None:
    if not (state.is_insert or state.is_update) or state.bind_mapper is None:
        return
    expected = GRADE_BY_MODEL.get(state.bind_mapper.class_)
    if expected is None:
        return
    if any(v != expected.value for v in _statement_grades(state)):
        raise GradeChangeForbidden(f"{state.bind_mapper.class_.__tablename__}.grade 변경 불가")
