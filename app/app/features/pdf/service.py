"""B12 자소서 PDF 생성·저장·다운로드(spec 3.2).

흐름: 고른 버전(없으면 문항별 최신) → HTML(기본 템플릿) → PDF → S3 비공개 저장(B6, KMS)
     → 1회용 다운로드 토큰(B6, 10분·다운로드 기록). 본문 개인정보는 가린 채로(토큰 복원 안 함).
멘토는 작성자 자소서에 접근할 수 없으므로(본인 소유만 조회) PDF를 만들 수 없다.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.storage import objects, tokens
from app.features.pdf.render import Contact, Item, build_html, render_pdf
from app.features.resumes import pii_hooks
from app.features.resumes import repository as resume_repo

CONTENT_TYPE = "application/pdf"
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')


class NothingToExport(ValueError):
    """저장된 문항 본문이 없다."""


class VersionsInvalid(ValueError):
    """고른 버전이 이 자소서 문항의 것이 아니거나, 한 문항에서 둘 이상 골랐다."""


@dataclass(frozen=True)
class Exported:
    token: str
    expires_at: datetime
    filename: str


def _items(
    db: Session, owner_id: str, resume_id: uuid.UUID, version_ids: list[uuid.UUID] | None
) -> list[Item]:
    questions = resume_repo.list_questions(db, owner_id, resume_id)
    by_q = {q.id: q for q in questions}
    if version_ids is None:
        latest = resume_repo.latest_versions(db, list(by_q))
        chosen = {qid: v for qid, v in latest.items()}
    else:
        chosen = {}
        for vid in dict.fromkeys(version_ids):
            v = resume_repo.get_version_any_question(db, owner_id, vid)
            if v is None or v.question_id not in by_q or v.question_id in chosen:
                raise VersionsInvalid()
            chosen[v.question_id] = v
    # 문항 순서대로. 본문은 저장된 토큰 상태 그대로 넘긴다(렌더러가 가린다)
    return [Item(q.title, chosen[q.id].body, q.char_limit) for q in questions if q.id in chosen]


def filename_for(title: str) -> str:
    name = _UNSAFE_NAME.sub(" ", title).strip()[:80] or "자기소개서"
    return f"{name}.pdf"


def export_pdf(
    db: Session, owner_id: str, resume_id: uuid.UUID, *,
    version_ids: list[uuid.UUID] | None = None, contact: Contact = Contact(),
) -> Exported | None:
    """PDF를 만들어 저장하고 다운로드 토큰을 준다. 자소서가 없거나 남의 것이면 None."""
    resume = resume_repo.get_resume(db, owner_id, resume_id)
    if resume is None:
        return None
    for value in (contact.name, contact.phone, contact.email):  # 주민번호 등은 PDF에도 넣지 않는다
        if value:
            pii_hooks.ensure_no_sensitive(value)
    items = _items(db, owner_id, resume_id, version_ids)
    if not items:
        raise NothingToExport()
    pdf = render_pdf(build_html(resume.title, items, contact))
    key = objects.user_object_key(owner_id, "resumes", str(resume_id), f"{uuid.uuid4()}.pdf")
    objects.put_object(key, pdf, CONTENT_TYPE)
    filename = filename_for(resume.title)
    token, expires_at = tokens.issue(db, owner_id, key, filename, CONTENT_TYPE)
    return Exported(token, expires_at, filename)
