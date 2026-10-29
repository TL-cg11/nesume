"""C10 — 사용자 근거 모으기: 자소서 1건 본문 + 본인 경험 → A11 `UserEvidence`.

맞춤 학습(`/learning-gaps`)과 자소서별 공고 추천(`/recommendations` resume_id)이 같이 쓴다.
B가 연 읽기 창구만 쓴다 — `resumes.reader.resume_bodies`(소유자 확인·원문 복원),
`experiences.reader.list_owner_experiences`. 본문은 서버 안에서만 쓰고 응답·로그에 싣지 않는다.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.features.matching.coverage import ExperienceRef, UserEvidence
from app.features.matching.vocab import matched_keys

#: 경험은 최근 것부터 이만큼만(대조 근거로 충분, 요청 비용 상한)
MAX_EXPERIENCES = 50


def _as_terms(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value if v)
    return (str(value),) if value else ()


def gather_evidence(session: Session, *, owner_id: str, resume_id: uuid.UUID) -> UserEvidence | None:
    """자소서가 없거나 남의 것이면 None(호출측이 404). 버전 없는 문항은 건너뛴다."""
    from app.features.experiences.reader import list_owner_experiences
    from app.features.resumes.reader import resume_bodies

    bodies = resume_bodies(session, owner_id, resume_id)
    if bodies is None:
        return None
    resume_text = "\n\n".join(b["body"] for b in bodies if b.get("body"))
    experiences = tuple(
        ExperienceRef(
            label=e.get("title") or "경험",
            text=" ".join(str(e.get(k) or "") for k in ("role", "outcome", "detail")).strip(),
            terms=_as_terms(e.get("tech_stack")) + _as_terms(e.get("tags")),
        )
        for e in list_owner_experiences(session, owner_id, limit=MAX_EXPERIENCES)
    )
    return UserEvidence(resume_text=resume_text, experiences=experiences)


def held_keys_of(evidence: UserEvidence) -> list[str]:
    """근거에 나온 A11 사전 키(자소서 본문 + 경험 글·기술) — 추천 키워드 점수용."""
    keys = set(matched_keys(evidence.resume_text))
    for e in evidence.experiences:
        keys |= matched_keys(" ".join((e.label, e.text, *e.terms)))
    return sorted(keys)
