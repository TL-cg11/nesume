"""C10 맞춤 학습 갭·자소서별 추천·공고 상세 테스트.

- `/learning-gaps`: B 창구(자소서 본문·경험)와 C4 창구만 바꿔치기, A11 규칙 대조·C10 정리는 **실제 코드**.
- 자소서별 쿼리 벡터·공고 상세 권한: DB 필요(conftest `db_session`).
"""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.features.matching.coverage import ExperienceRef, UserEvidence
from app.features.recommend.service import gather_query_vectors
from app.features.skill_gap import router as gaps_router
from app.features.skill_gap.evidence import held_keys_of
from app.features.skill_gap.router import LearningGapsRequest, learning_gaps_for
from app.models.embedding import EMBED_DIM, MODEL_VERSION, UserProfileEmbedding
from app.models.posting import JobPosting
from app.models.user import User
from app.postings.read import get_posting_detail
from app.postings.work24_open import parse_detail, parse_xml

_POSTING = {
    "title": "클라우드 보안 엔지니어",
    "job_name": "정보보안",
    "job_content": "AWS 클라우드 환경에서 Docker 컨테이너와 Linux 서버를 운영합니다.",
    "certificates": "정보보안기사",
    "preferred": "Kubernetes 운영 경험 우대",
    "major": None,
    "computer_skills": "AWS, Docker, Linux, Kubernetes",
}
USER = SimpleNamespace(sub="user-1")


def _call(monkeypatch, evidence, posting=_POSTING):
    monkeypatch.setattr(gaps_router, "gather_evidence", lambda db, owner_id, resume_id: evidence)
    monkeypatch.setattr(gaps_router, "get_posting_fields", lambda db, pid, user_id: posting)
    req = LearningGapsRequest(resume_id=uuid.uuid4(), posting_id=uuid.uuid4())
    return learning_gaps_for(req, USER, db=None)


# --------------------------------------------------------------------------
# /learning-gaps
# --------------------------------------------------------------------------

def test_gaps_are_what_resume_and_experience_lack(monkeypatch):
    """자소서에 AWS, 경험에 Docker → 둘 다 갭이 아니다. 나머지(Linux 등)만 배울 것."""
    evidence = UserEvidence(
        resume_text="AWS로 보안 인프라를 운영했습니다.",
        experiences=(ExperienceRef(label="사내 프로젝트", text="컨테이너 운영", terms=("Docker",)),),
    )
    out = _call(monkeypatch, evidence)
    keys = {g.key for g in out.gaps}
    assert keys, "공고 요건 중 부족한 것이 있어야 한다"
    assert not {"aws", "docker"} & keys  # 자소서·경험에 있는 건 갭 아님
    assert all(g.importance in ("required", "preferred") for g in out.gaps)  # 언급(mentioned) 제외
    assert out.counts["covered"] + out.counts.get("in_experience_only", 0) >= 2


def test_gaps_empty_evidence_lists_requirements(monkeypatch):
    out = _call(monkeypatch, UserEvidence())
    assert out.gaps and out.counts["missing"] >= len(out.gaps)


def test_gaps_order_required_first(monkeypatch):
    out = _call(monkeypatch, UserEvidence())
    ranks = [{"required": 0, "preferred": 1}[g.importance] for g in out.gaps]
    assert ranks == sorted(ranks)


@pytest.mark.parametrize("missing", ["resume", "posting"])
def test_gaps_404_when_not_owner_or_missing(monkeypatch, missing):
    evidence = None if missing == "resume" else UserEvidence()
    posting = None if missing == "posting" else _POSTING
    with pytest.raises(HTTPException) as ei:
        _call(monkeypatch, evidence, posting)
    assert ei.value.status_code == 404


def test_held_keys_from_resume_and_experiences():
    ev = UserEvidence(
        resume_text="AWS 경험",
        experiences=(ExperienceRef(label="x", text="", terms=("Docker",)),),
    )
    assert {"aws", "docker"} <= set(held_keys_of(ev))


def test_routes_registered():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert {"/learning-gaps", "/postings/{posting_id}"} <= paths


# --------------------------------------------------------------------------
# 공채속보 경력·학력 파싱 (순수)
# --------------------------------------------------------------------------

def test_work24_open_career_edu_text():
    xml = b"""<dhsOpenEmpInfoDetailRoot><empSeqno>1</empSeqno><empWantedTitle>t</empWantedTitle>
    <empRecrList>
      <empRecrListInfo><empRecrNm>A</empRecrNm><empWantedCareerNm>\xec\x8b\xa0\xec\x9e\x85</empWantedCareerNm>
        <empWantedEduNm>\xeb\x8c\x80\xec\xa1\xb8</empWantedEduNm></empRecrListInfo>
      <empRecrListInfo><empRecrNm>B</empRecrNm><empWantedCareerNm>\xea\xb2\xbd\xeb\xa0\xa5</empWantedCareerNm>
        <empWantedEduNm>\xeb\x8c\x80\xec\xa1\xb8</empWantedEduNm></empRecrListInfo>
    </empRecrList></dhsOpenEmpInfoDetailRoot>"""
    f = parse_detail(parse_xml(xml))
    assert f["career_text"] == "신입 / 경력"  # 분야별 값, 중복 제거
    assert f["edu_text"] == "대졸"


def test_seoul_career_edu_text():
    from app.postings.collect import parse_seoul_row

    f = parse_seoul_row({"CAREER": "경력(2년 이상)", "MIN_EDUBG": "대졸(4년)", "MAX_EDUBG": "석사"})
    assert f["career_text"] == "경력(2년 이상)"
    assert f["edu_text"] == "대졸(4년)~석사"
    assert parse_seoul_row({"MIN_EDUBG": "학력무관", "MAX_EDUBG": "학력무관"})["edu_text"] == "학력무관"


# --------------------------------------------------------------------------
# DB — 자소서별 쿼리 벡터 · 공고 상세 권한
# --------------------------------------------------------------------------

def _user(session):
    uid = str(uuid.uuid4())
    session.add(User(id=uid))
    session.flush()
    return uid


def _vec(i):
    v = [0.0] * EMBED_DIM
    v[i] = 1.0
    return v


def test_query_vectors_filtered_by_resume(db_session):
    me, other = _user(db_session), _user(db_session)
    r1, r2 = uuid.uuid4(), uuid.uuid4()
    rows = [
        (me, r1, "resume", 0),
        (me, r2, "resume", 1),
        (me, uuid.uuid4(), "experience", 2),
        (other, r1, "resume", 3),
    ]
    for owner, sid, kind, i in rows:
        db_session.add(UserProfileEmbedding(owner_id=owner, source_type=kind, source_id=sid, content="x",
                                            model_version=MODEL_VERSION, embedding=_vec(i)))
    db_session.flush()

    assert len(gather_query_vectors(db_session, me)) == 3  # 기존: 전체
    only = gather_query_vectors(db_session, me, r1)
    assert len(only) == 1 and list(only[0])[0] == 1.0  # 내 r1만(남의 같은 id·경험 제외)


def test_posting_detail_fields_and_owner_rule(db_session):
    owner = _user(db_session)
    pub = JobPosting(source="work24_open", link_key=str(uuid.uuid4()), content_hash="h1", title="공개",
                     career_text="신입", edu_text="대졸", apply_method="온라인", job_content="직무 원문",
                     source_url="https://x.example.com/1")
    mine = JobPosting(source="user", link_key=str(uuid.uuid4()), content_hash="h2", title="내 공고",
                      owner_user_id=owner)
    db_session.add_all([pub, mine])
    db_session.flush()

    d = get_posting_detail(db_session, pub.id, user_id="anyone")
    labels = [f["label"] for f in d["fields"]]
    assert labels == ["경력", "학력", "접수방법"]  # 값 있는 것만, 화면 순서
    assert d["job_content"] == "직무 원문" and d["url"] == "https://x.example.com/1"
    assert get_posting_detail(db_session, mine.id, user_id="someone-else") is None  # 남의 비공개 공고
    assert get_posting_detail(db_session, mine.id, user_id=owner)["title"] == "내 공고"


def test_unchanged_posting_backfills_new_display_columns(db_session):
    """0018 이전에 수집된 공고: 내용(해시)이 같아도 비어 있던 경력·학력은 다음 수집 때 채워진다."""
    from app.postings.upsert import upsert_posting

    base = {"source_key": "S-1", "company_name": "회사", "title": "공고", "job_content": "본문"}
    row, _ = upsert_posting(db_session, source="work24_open", fields=base)
    db_session.flush()
    assert row.career_text is None

    again, action = upsert_posting(db_session, source="work24_open",
                                   fields={**base, "career_text": "신입", "edu_text": "대졸"})
    assert action.value == "unchanged" and again.id == row.id
    assert (again.career_text, again.edu_text) == ("신입", "대졸")

    upsert_posting(db_session, source="work24_open", fields={**base, "career_text": "경력"})
    assert again.career_text == "신입"  # 이미 있으면 덮어쓰지 않음(무변경 공고)


def test_roadmap_explain_uses_shared_guardrail_with_audit():
    """C14 설명 LLM 경로는 앱 공유 가드레일 — 감사 로그(B11)가 붙고, D가 주입한 LLM 제공자를 같이 쓴다."""
    from app.features.roadmap.router import get_guardrail as roadmap_guardrail
    from app.guardrail.fastapi import get_guardrail as shared

    g = roadmap_guardrail()
    assert g is shared()
    assert g.audit is not None


def test_required_keys_only_vocab_terms():
    """키워드율 분모 = 사전 기술만. 병역·경력 연수 같은 other 조각은 빠진다."""
    from app.features.recommend.service import _a11_required_keys

    keys = _a11_required_keys({
        "title": "백엔드 개발자",
        "job_content": "Python, SQL 사용. 병역필 또는 면제자. 경력 3년 이상",
        "certificates": None, "preferred": None, "major": None, "computer_skills": None, "job_name": None,
    })
    assert {"python", "sql"} <= set(keys)
    assert not any("병역" in k or "경력" in k for k in keys)


def test_work24_open_unescapes_double_encoded_entities():
    xml = (b"<dhsOpenEmpInfoDetailRoot><empSeqno>1</empSeqno>"
           b"<empWantedTitle>A&amp;apos;s &amp;amp; B</empWantedTitle></dhsOpenEmpInfoDetailRoot>")
    assert parse_detail(parse_xml(xml))["title"] == "A's & B"


# --------------------------------------------------------------------------
# 3종 분류 — 기술 역량 / 직무 역량 / 지원 조건 (실측 조각 그대로)
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("병역필(접수마감일 기준", "병역"),
        ("면제자", "병역"),
        ("학력 : 대학교(학사)졸 이상", "학력"),
        ("경력 7년 이하", "경력"),
        ("17 계리결산 관련 업무 경력 3년 이상", "경력"),
        ("성별 제한 없음", "인적사항"),
        ("해외여행에 결격 사유가 없는 자", "결격"),
        ("관련전공 : 전공 무관", "전공"),
    ],
)
def test_conditions_detected(text, kind):
    from app.features.skill_gap.classify import CONDITION, kind_of

    assert kind_of(text, "other") == (CONDITION, kind)


@pytest.mark.parametrize("text", ["IFRS17", "K-ICS 계리결산에 대한 실무적 이해", "계리소프트웨어", "MATLAB"])
def test_domain_competencies_kept(text):
    from app.features.skill_gap.classify import DOMAIN, kind_of

    assert kind_of(text, "other") == (DOMAIN, None)


@pytest.mark.parametrize("text", ["응시자격", "&apos", "등", "A"])
def test_noise_dropped(text):
    from app.features.skill_gap.classify import NOISE, kind_of

    assert kind_of(text, "other")[0] == NOISE


def test_vocab_terms_always_skill():
    from app.features.skill_gap.classify import SKILL, kind_of

    assert kind_of("Python", "language") == (SKILL, None)


def test_gaps_split_skill_domain_conditions_covered(monkeypatch):
    # 실제 공고 모양: A11은 자격·우대 필드에서 문장 조각을, 컴퓨터 활용에서 기술을 뽑는다
    posting = {
        **_POSTING,
        "job_content": "데이터 분석 업무",
        "computer_skills": "Python, SQL",
        "certificates": "- 병역필 또는 면제자\n- 학력 : 대졸 이상",
        "preferred": "- IFRS17 결산 경험",
    }
    evidence = UserEvidence(resume_text="Python으로 데이터 분석을 했습니다.")
    out = _call(monkeypatch, evidence, posting)

    skill_keys = {g.key for g in out.gaps}
    assert "sql" in skill_keys and "python" not in skill_keys  # 자소서에 있는 python은 갭 아님
    assert all("병역" not in g.label and "학력" not in g.label for g in out.gaps + out.domain_gaps)
    assert {c.kind for c in out.conditions} >= {"병역"}
    assert any("IFRS17" in g.label for g in out.domain_gaps)
    assert any(c.label == "Python" and c.status == "covered" for c in out.covered)
