"""A6 리라이팅 서비스 — 후보 만들기와 고른 후보 저장.

## ★ 가드레일에는 **사용자가 고른 글**을 그대로 넘긴다

A7·A11·A13 은 프롬프트를 먼저 조립해서 `guard.run()` 에 넘긴다. 그러면 A3·A12 가
우리가 만든 템플릿까지 검사 대상으로 보게 되고, **문장 전체를 보는 규칙은 죽는다**
(A12 `is_continuation` 이 그래서 `A10-MULTI-04` 를 놓쳤다).

여기서는 사용자 글만 넘기고, 조립은 A8 안쪽 `PartsBuilder` 에서 한다. 기존 세 기능도
같은 모양으로 옮겨야 하지만 그건 따로 고친다.

## ★ 저장은 B4 서비스 함수로 한다

B4 의 HTTP 엔드포인트는 `source` 를 `"manual"` 로 못박아 두었다
(`resumes.schemas.VersionCreate`: "AI 버전은 A6이 서비스 함수로 저장"). 그래서
A6 가 자기 엔드포인트에서 `create_version(..., source="ai")` 를 부른다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.features.profile import service as profile_service
from app.features.profile.store import ProfileStore
from app.features.resumes import service as resumes_service
from app.features.style import tone as tone_mod
from app.features.style.service import invented_numbers
from app.features.style.tone import TONE_NAMES
from app.features.templates import service as templates_service
from app.features.writing.rewrite import (
    CANDIDATE_COUNT,
    MAX_PARTS,
    MAX_SAMPLE_CHARS,
    MIN_SAMPLE_CHARS,
    SAMPLE_RULE,
    SAMPLE_SEP,
    RewriteOptionError,
    RewriteOptions,
    build_part_prompt,
    join_candidates,
    parse_candidates,
    sample_measures,
    split_selection,
)
from app.guardrail import Guardrail, LlmUnavailable, PipelineResult, RequestContext

#: B9 활성 템플릿 이름. **A 가 정해 운영자에게 알린다** (docs/B9.md 6장).
TEMPLATE_NAME = "rewrite-default"

#: 이 기능이 감사 로그에 남기는 이름.
#:
#: ★ **B15 취합 시트(`eval/scenarios_sheet.yaml`)가 쓰는 값과 같아야 한다.**
#:   평가 러너는 시트의 `feature` 로 보낼 API 를 고르고, 판정은 감사 로그에서 읽는다.
#:   두 값이 어긋나면 보내기는 맞게 보내도 **로그를 찾지 못한다.**
#:   시트가 `rewrite.generate` 로 적어 두었으므로 그쪽에 맞춘다
#:   (`matching.analyze`·`style.adjust` 와 같은 `<기능>.<동작>` 꼴이기도 하다).
FEATURE = "rewrite.generate"


@dataclass(frozen=True)
class Candidate:
    """후보 하나와 원문 대비 차이."""

    body: str
    #: 단어 단위 차이. B4 `diff_segments` 와 **같은 함수**를 쓴다 —
    #: 여기서 또 만들면 같은 글에 대해 두 화면이 다른 차이를 보여준다
    segments: list[dict]


@dataclass(frozen=True)
class RewriteResult:
    candidates: tuple[Candidate, ...] = ()
    #: 모델에 간 지시문. A14 와 같은 생각이다 — 무엇이 갔는지 사용자가 볼 수 있어야 한다
    instructions: str = ""
    #: 나눠 보낸 조각 수. 1 이면 나누지 않았다
    parts: int = 1
    llm_used: bool = False
    llm_unavailable: bool = False
    blocked_reason: str | None = None
    #: 화면에 그대로 띄울 안내. 기능은 돌았지만 사용자가 알아야 하는 것
    notices: tuple[str, ...] = field(default_factory=tuple)


def _template_body(db: Session) -> tuple[str | None, tuple[str, ...]]:
    """B9 활성 템플릿 본문. 쓸 수 없으면 ``None`` 과 안내를 돌려준다.

    ★ 활성 템플릿이 없다고 기능이 멈추면 안 된다. 운영자가 첫 템플릿을 등록하기
      전까지 아무도 리라이팅을 못 쓰게 된다 — 내장 기본값으로 돈다.

    ★ 변수가 있는 템플릿은 **쓰지 않는다.** B9 `render` 는 변수 이름이 정확히 같아야
      하고(빠짐·남음 모두 거부), A6 가 채울 수 있는 변수를 정해 두지 않았다.
      억지로 빈 값을 넣으면 프롬프트에 빈 칸이 생긴 채 모델에 간다.
    """
    template = templates_service.get_active_template(db, TEMPLATE_NAME)
    if template is None:
        return None, (
            "운영자가 등록한 리라이팅 프롬프트가 없어 기본 프롬프트로 처리했습니다.",
        )
    if template.variables:
        return None, (
            f"'{TEMPLATE_NAME}' 템플릿이 변수를 요구해 기본 프롬프트로 처리했습니다.",
        )
    return templates_service.render(template, {}), ()


async def rewrite(
    db: Session,
    text: str,
    options: RewriteOptions,
    *,
    guard: Guardrail,
    store: ProfileStore,
    user_id: str,
    role: str,
    session_id: str = "",
    is_test: bool = False,
    request_id: uuid.UUID | None = None,
    use_llm: bool = True,
    style_sample: str | None = None,
) -> RewriteResult:
    """고른 구간을 다시 쓴 후보를 만든다. **저장하지 않는다.**

    ``style_sample`` 이 있으면 그 글의 말투로 다시 쓴다(저장된 말투 프로필 대신).
    """
    sample = (style_sample or "").strip()
    if sample and len(sample) < MIN_SAMPLE_CHARS:
        raise RewriteOptionError(f"말투 샘플은 {MIN_SAMPLE_CHARS}자 이상이어야 합니다")
    if len(sample) > MAX_SAMPLE_CHARS:
        raise RewriteOptionError(f"말투 샘플은 {MAX_SAMPLE_CHARS}자까지입니다")

    instructions = options.instructions()
    measures = sample_measures(sample, text) if sample else ""
    if sample:
        instructions += f"\n{SAMPLE_RULE}\n{measures}"
    if not use_llm:
        # 화면이 옵션만 바꿔 보는 경우. 모델을 부르지 않는다
        return RewriteResult(instructions=instructions)

    body, notices = _template_body(db)
    fragment = "" if sample else profile_service.prompt_fragment(
        profile_service.get(user_id, store=store)
    )
    parts_count = len(split_selection(text))

    def parts(tokenized: str) -> list[str]:
        """치환이 끝난 글을 조각내 조각별 프롬프트로 바꾼다.

        ★ 조각내기는 **치환된 글** 기준이다. 원문을 조각내면 토큰이 조각 경계에서
          잘려 복원되지 않는다 — ``[[PERSON_`` 과 ``1]]`` 은 토큰이 아니다.
        ★ 샘플이 있으면 ``샘플 + SAMPLE_SEP + 글`` 이 치환되어 온다. 경계에서 갈라
          샘플은 조각마다 붙이고 글만 조각낸다.
        """
        tok_sample, tok_text = "", tokenized
        if sample and SAMPLE_SEP in tokenized:
            tok_sample, tok_text = tokenized.split(SAMPLE_SEP, 1)
        pieces = split_selection(tok_text)
        return [
            build_part_prompt(
                piece, options,
                template_body=body, profile_fragment=fragment,
                style_sample=tok_sample, sample_measures=measures,
                part_index=i, part_total=len(pieces),
            )
            for i, piece in enumerate(pieces)
        ]

    ctx = RequestContext(
        user_id=user_id, role=role, feature=FEATURE,
        session_id=session_id, is_test=is_test,
        request_id=request_id or uuid.uuid4(),
    )
    # ★ 샘플도 검사·치환 대상이다. 따로 붙이면 샘플 속 PII 가 가려지지 않는다 (rewrite.SAMPLE_SEP)
    query = f"{sample}{SAMPLE_SEP}{text}" if sample else text
    try:
        result: PipelineResult = await guard.run_split(query, ctx, parts=parts)
    except LlmUnavailable:
        # 제공자 미정(2026-10). A7·A11·A13 과 같은 처리 — 사용자가 빈손으로 끝나지 않는다
        return RewriteResult(instructions=instructions, parts=parts_count, llm_unavailable=True)

    if result.blocked:
        return RewriteResult(
            instructions=instructions, parts=parts_count, llm_used=True,
            blocked_reason=result.verdict.rule_id or "차단되었습니다",
        )

    per_part = [parse_candidates(part) for part in result.parts]
    bodies = join_candidates(per_part)
    if sample and bodies:
        # ★ 샘플의 숫자가 본문에 섞이면 그건 이 경험의 사실이 아니다. 후보째 버린다
        #   (A13 verify_rewrite 와 같은 판단 — 다시 쓴 글은 일부만 믿을 수 없다)
        kept = tuple(b for b in bodies if not invented_numbers(text, b))
        if len(kept) < len(bodies):
            notices += (
                f"원문에 없는 숫자가 들어간 후보 {len(bodies) - len(kept)}개를 뺐습니다.",
            )
        # ★ 샘플 끝맺음(했다·해요)이 문체 지시를 이기는 일이 잦다(10-29 실측). 고른 문체가
        #   아닌 문장이 남은 후보는 뺀다 — A13 이 바로 "문체가 섞였다" 로 짚을 글이다
        toned = tuple(b for b in kept if not tone_mod.analyze(b).off_tone(options.tone))
        if len(toned) < len(kept):
            notices += (
                f"{TONE_NAMES[options.tone]}가 아닌 문장이 섞인 후보 {len(kept) - len(toned)}개를 뺐습니다.",
            )
        bodies = toned
    if not bodies:
        # 모델이 형식을 어겼다. 응답 전체를 후보로 치지 않는다 —
        # 사과문이나 설명문이 자소서 본문으로 저장된다
        notices += ("모델이 후보를 형식대로 주지 않아 결과를 만들지 못했습니다. 다시 시도해 주세요.",)
    elif len(bodies) < CANDIDATE_COUNT:
        notices += (f"후보 {CANDIDATE_COUNT}개 중 {len(bodies)}개만 만들어졌습니다.",)

    return RewriteResult(
        candidates=tuple(
            Candidate(body=b, segments=resumes_service.diff_segments(text, b)) for b in bodies
        ),
        instructions=instructions,
        parts=parts_count,
        llm_used=True,
        notices=notices,
    )


def apply_candidate(
    db: Session,
    *,
    owner_id: str,
    resume_id: uuid.UUID,
    question_id: uuid.UUID,
    body: str,
):
    """고른 후보를 **새 버전**으로 저장한다 (tasks.md A6 "후보 선택 시 새 버전 저장(B4)").

    ★ B4 서비스 함수를 그대로 부른다. 여기서 Version 을 직접 만들면 등급 부여(B8)·
      민감정보 차단·버전 상한·인덱싱이 전부 빠진다 — B4 가 그 자리에서 하는 일이다.

    ★ `source="ai"` 다. B4 의 HTTP 엔드포인트는 `"manual"` 로 못박혀 있어
      (`resumes.schemas.VersionCreate`) 이 경로로만 AI 버전이 생긴다. 나중에
      "AI 가 쓴 글이 얼마나 저장됐나" 를 세려면 이 값이 유일한 근거다.

    돌려주는 것은 B4 와 같다 — 문항이 없거나 타인 소유면 ``None``.
    민감정보는 `pii_hooks.SensitiveInputBlocked`, 상한은 `VersionLimitReached`.
    """
    return resumes_service.create_version(
        db, owner_id, resume_id, question_id, body, "ai"
    )


__all__ = [
    "Candidate",
    "FEATURE",
    "MAX_PARTS",
    "RewriteResult",
    "TEMPLATE_NAME",
    "apply_candidate",
    "rewrite",
]
