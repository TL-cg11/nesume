"""프롬프트 템플릿 (tasks B9, spec 3.6, part2_guide 4.52).

- 운영자만 생성·새 버전 작성(require_role OPERATOR). 활성 전환은 운영자 MFA 세션(require_operator_mfa)
- 수정은 새 버전 생성(덮어쓰기 없음). 이름별 활성 버전은 최대 1개(DB 부분 유일 인덱스)
- 본문 변수는 `{{변수}}`. 저장할 때 본문의 변수와 변수 목록이 정확히 같아야 한다
- 내부 등급(B8 자동 부여). 검색 인덱스에 넣지 않고 HTTP로 사용자에게 열지 않는다
- A(작성 AI)는 같은 앱 안에서 `get_active_template` / `render`로 활성 버전만 읽는다(사용자 결정 10/27)
"""
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import PromptTemplate

VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]{0,49})\s*\}\}")
VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,49}$")


class TemplateExists(ValueError):
    pass


class VariablesMismatch(ValueError):
    def __init__(self, missing: set[str], unused: set[str]):
        self.missing, self.unused = missing, unused  # 본문에만 있음 / 목록에만 있음
        super().__init__()


class RenderValuesMismatch(ValueError):
    pass


@dataclass(frozen=True)
class ActiveTemplate:
    name: str
    purpose: str
    version: int
    body: str
    variables: tuple[str, ...]


def placeholders(body: str) -> set[str]:
    return set(VARIABLE.findall(body))


def check_variables(body: str, variables: list[str]) -> None:
    used, declared = placeholders(body), set(variables)
    if used != declared or len(variables) != len(declared):
        raise VariablesMismatch(missing=used - declared, unused=declared - used)


def _next_version(db: Session, name: str) -> int:
    return (db.scalar(select(func.max(PromptTemplate.version)).where(PromptTemplate.name == name)) or 0) + 1


def create(db: Session, operator_id: str, *, name: str, purpose: str, body: str, variables: list[str]) -> PromptTemplate:
    """새 템플릿(1버전, 비활성)."""
    if db.scalar(select(PromptTemplate.id).where(PromptTemplate.name == name).limit(1)):
        raise TemplateExists()
    check_variables(body, variables)
    t = PromptTemplate(name=name, purpose=purpose, body=body, variables=list(variables), version=1,
                       created_by=operator_id)
    db.add(t)
    db.flush()
    db.refresh(t)
    return t


def new_version(db: Session, operator_id: str, name: str, *, body: str, variables: list[str],
                purpose: str | None = None) -> PromptTemplate | None:
    """새 버전(비활성). 템플릿이 없으면 None. 용도를 안 주면 직전 버전 값을 쓴다."""
    latest = db.scalar(select(PromptTemplate).where(PromptTemplate.name == name)
                       .order_by(PromptTemplate.version.desc()).limit(1).with_for_update())
    if latest is None:
        return None
    check_variables(body, variables)
    t = PromptTemplate(name=name, purpose=purpose or latest.purpose, body=body, variables=list(variables),
                       version=_next_version(db, name), created_by=operator_id)
    db.add(t)
    db.flush()
    db.refresh(t)
    return t


def activate(db: Session, template_id: uuid.UUID) -> PromptTemplate | None:
    """이 버전을 활성으로, 같은 이름의 다른 버전은 비활성으로(유일 인덱스라 먼저 끈다)."""
    t = db.get(PromptTemplate, template_id, with_for_update=True)
    if t is None:
        return None
    db.execute(update(PromptTemplate).where(PromptTemplate.name == t.name, PromptTemplate.id != t.id)
               .values(is_active=False))
    db.flush()
    t.is_active = True
    db.flush()
    db.refresh(t)
    return t


def list_names(db: Session) -> list[dict]:
    """이름별 요약: 최신 버전, 활성 버전, 용도."""
    rows = db.execute(select(PromptTemplate.name, PromptTemplate.purpose, PromptTemplate.version,
                             PromptTemplate.is_active).order_by(PromptTemplate.name, PromptTemplate.version)).all()
    out: dict[str, dict] = {}
    for name, purpose, version, active in rows:
        cur = out.setdefault(name, {"name": name, "purpose": purpose, "latest_version": 0, "active_version": None})
        cur["latest_version"], cur["purpose"] = version, purpose
        if active:
            cur["active_version"] = version
    return list(out.values())


def list_versions(db: Session, name: str) -> list[PromptTemplate]:
    return list(db.scalars(select(PromptTemplate).where(PromptTemplate.name == name)
                           .order_by(PromptTemplate.version.desc())).all())


# --- A(작성 AI)용 읽기 함수 -----------------------------------------------------

def get_active_template(db: Session, name: str) -> ActiveTemplate | None:
    """활성 버전만. 활성 버전이 없으면 None(호출자가 기본 프롬프트로 대체할지 결정)."""
    t = db.scalar(select(PromptTemplate).where(PromptTemplate.name == name, PromptTemplate.is_active.is_(True)))
    if t is None:
        return None
    return ActiveTemplate(name=t.name, purpose=t.purpose, version=t.version, body=t.body,
                          variables=tuple(t.variables))


def render(template: ActiveTemplate, values: dict[str, str]) -> str:
    """`{{변수}}`를 채운다. 넘긴 값의 이름이 변수 목록과 정확히 같아야 한다(빠짐·남음 모두 거부)."""
    if set(values) != set(template.variables):
        raise RenderValuesMismatch(f"필요: {sorted(template.variables)}, 받음: {sorted(values)}")
    return VARIABLE.sub(lambda m: str(values[m.group(1)]), template.body)
