"""A11 대조 — 세 갈래로 나누는 것이 이 기능의 값이다."""

from __future__ import annotations

from app.features.matching.coverage import (
    MIN_KEYWORDS_FOR_RATE,
    ExperienceRef,
    UserEvidence,
    compare,
)
from app.features.matching.keywords import PostingFields, extract

POSTING = PostingFields(
    certificates="정보처리기사",
    computer_skills="엑셀",
    job_content="Django 와 Docker 를 씁니다.",
)


def statuses(report) -> dict[str, str]:
    return {m.keyword.text: m.status for m in report.matches}


def test_three_way_split() -> None:
    report = compare(
        extract(POSTING),
        UserEvidence(
            resume_text="Django 로 API 를 만들었습니다.",
            experiences=(
                ExperienceRef(label="배포 자동화", text="도커로 배포했습니다", terms=("정보처리기사",)),
            ),
        ),
    )

    got = statuses(report)
    assert got["Django"] == "covered", "자소서에 썼다"
    assert got["Docker"] == "in_experience_only", "경험엔 있는데 자소서에 안 썼다"
    assert got["정보처리기사"] == "in_experience_only", "태그에 있다"
    assert got["엑셀"] == "missing", "아무 데도 없다"


def test_in_experience_only_carries_the_evidence() -> None:
    """★ 사용자가 사실 확인을 할 수 있어야 한다 — 어느 경험에서 나왔는지 보여준다."""
    report = compare(
        extract(PostingFields(job_content="Docker 사용")),
        UserEvidence(experiences=(ExperienceRef(label="배포 자동화", text="도커 사용"),)),
    )
    assert report.matches[0].experiences == ("배포 자동화",)


def test_cross_notation_match_between_posting_and_experience() -> None:
    """공고는 "Docker", 경험은 "도커" 라고 적는다. 글자로 비교하면 못 찾는다."""
    report = compare(
        extract(PostingFields(job_content="Docker 로 배포")),
        UserEvidence(experiences=(ExperienceRef(label="e", text="도커로 배포"),)),
    )
    assert report.matches[0].status == "in_experience_only"


# ---------------------------------------------------------------- 비율

def test_required_rate_counts_only_what_is_written_in_the_resume() -> None:
    """★ 가지고 있다는 것과 전달했다는 것은 다르다.

    경험에만 있는 요건을 달성으로 세면 "다 썼다" 고 믿고 제출한다.
    """
    report = compare(
        extract(PostingFields(certificates="정보처리기사", computer_skills="엑셀")),
        UserEvidence(
            resume_text="엑셀로 집계했습니다",
            experiences=(ExperienceRef(label="e", terms=("정보처리기사",)),),
        ),
    )
    assert report.required_rate == 0.5


def test_required_rate_is_none_without_required_keywords() -> None:
    report = compare(extract(PostingFields(job_content="Docker 사용")), UserEvidence())
    assert report.required_rate is None, "필수 요건이 없으면 비율이 없다"


def test_rate_is_flagged_unreliable_when_there_are_few_keywords() -> None:
    """★ 키워드 2개인 공고의 "50%" 는 아무 뜻이 없다. 숫자만 내보내면 목표로 삼는다."""
    few = compare(extract(PostingFields(certificates="정보처리기사")), UserEvidence())
    assert few.rate_reliable is False

    many = compare(extract(POSTING), UserEvidence())
    assert len(many.matches) >= MIN_KEYWORDS_FOR_RATE
    assert many.rate_reliable is True


# ---------------------------------------------------------------- 순서·토큰

def test_actionable_items_come_first() -> None:
    report = compare(
        extract(POSTING),
        UserEvidence(
            resume_text="Django 사용",
            experiences=(ExperienceRef(label="e", text="도커 사용"),),
        ),
    )
    order = [m.status for m in report.matches]
    assert order.index("in_experience_only") < order.index("missing") < order.index("covered")


def test_pii_tokens_are_not_restored_and_match_nothing() -> None:
    """★ 사용자 글은 토큰화 상태로 저장된다(B7). 대조에 원문 PII 가 필요 없다."""
    report = compare(
        extract(PostingFields(certificates="정보처리기사")),
        UserEvidence(resume_text="연락처는 [[PHONE_1]] 이고 이름은 [[PERSON_1]] 입니다."),
    )
    assert report.matches[0].status == "missing"


def test_empty_evidence_marks_everything_missing() -> None:
    report = compare(extract(POSTING), UserEvidence())
    assert set(statuses(report).values()) == {"missing"}


# ---------------------------------------------------------------- 택일 묶음

def test_major_alternatives_count_as_one_requirement() -> None:
    """★ MAJOR 의 "컴퓨터공학, 소프트웨어학과" 는 **둘 중 하나**다.

    따로 세면 전공을 맞춘 지원자도 달성률이 절반으로 나온다 — 숫자가 틀리면
    사용자가 엉뚱한 곳을 고친다.
    """
    report = compare(
        extract(PostingFields(major="컴퓨터공학, 소프트웨어학과")),
        UserEvidence(resume_text="컴퓨터공학을 전공했습니다"),
    )

    assert len(report.required) == 2, "요건은 둘 다 보여준다"
    assert len(report.required_units) == 1, "세는 단위는 하나다"
    assert report.required_rate == 1.0


def test_major_group_does_not_swallow_other_requirements() -> None:
    report = compare(
        extract(PostingFields(major="컴퓨터공학, 소프트웨어학과", certificates="정보처리기사")),
        UserEvidence(resume_text="컴퓨터공학을 전공했습니다"),
    )
    assert len(report.required_units) == 2, "전공 묶음 + 자격증"
    assert report.required_rate == 0.5


def test_requirement_in_both_major_and_prose_is_not_grouped() -> None:
    """줄글에서 따로 강조된 요건은 택일로 볼 수 없다.

    (사전 밖 전공은 줄글에서 찾을 수 없어 늘 묶인다 — 줄글은 사전으로만 보기 때문이다.)
    """
    got = {k.text: k for k in extract(PostingFields(
        major="회계학, 경영학", job_content="회계 업무를 담당합니다"
    ))}
    assert got["회계"].group is None, "줄글에도 적혀 있으면 택일이 아니다"
    assert got["경영학"].group == "major"
