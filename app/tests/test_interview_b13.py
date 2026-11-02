"""B13 모의 면접(대화형, 11/2 대체).

시작(무작위 페르소나 유지·본인 자료만), 꼬리/다음 진행과 상한, 종료·종합 피드백·예상 질문,
민감정보 차단, 모델 없음·차단 시 저장 안 함, 권한·삭제.
"""
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import CurrentUser, Role, get_current_user
from app.db import SessionLocal
from app.features.interview import service
from app.guardrail import Guardrail, LlmClient, LlmUnavailable
from app.guardrail.fastapi import get_guardrail
from app.main import app
from app.models import InterviewMessage, InterviewSession
from app.pii import InMemoryVaultStore
from tests.guardrail.fakes import FakeProvider

PHONE = "010-1234-5678"
FEEDBACK = ("구조: 결론이 먼저 나옵니다.\n구체성: 수치가 부족합니다.\n일관성: 자소서와 맞습니다.\n"
            "질문별:\n- 첫 질문: 좋음\n- 꼬리 질문: 근거 부족\n제안: 결과를 수치로.")
EXPECTED = "1. 지원 동기는?\n2. 가장 어려웠던 문제는?"


class Script:
    """프롬프트를 기록하고, 프롬프트 종류(시작·진행·피드백·예상 질문)에 맞는 답을 돌려주는 가드레일 대역."""

    def __init__(self, turns=("[꼬리]\n그때 본인 역할은?",), *, blocked=False, unavailable=False):
        self.turns, self.blocked, self.unavailable, self.prompts = list(turns), blocked, unavailable, []

    def reply(self, prompt):
        if "모의 면접 기록을 보고" in prompt:
            return FEEDBACK
        if "예상 질문" in prompt and "모의 면접의" not in prompt:
            return EXPECTED
        if "지금 면접을 시작합니다" in prompt:
            return "[다음]\n안녕하세요. 자기소개 부탁드립니다."
        return self.turns.pop(0) if len(self.turns) > 1 else self.turns[0]

    async def run(self, prompt, ctx):
        self.prompts.append((prompt, ctx))
        if self.unavailable:
            raise LlmUnavailable("no model")
        verdict = SimpleNamespace(decision="block" if self.blocked else "allow",
                                  rule_id="INJ-01" if self.blocked else None)
        return SimpleNamespace(text="" if self.blocked else self.reply(prompt), blocked=self.blocked,
                               verdict=verdict)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()


def _client(sub, guard, role=Role.USER):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub=sub, role=role)
    app.dependency_overrides[get_guardrail] = lambda: guard
    return TestClient(app)


def _resume(c, bodies=(f"결제 API 응답 시간을 40% 줄였습니다. 연락처 {PHONE}", "갈등 조정 경험")):
    r = c.post("/resumes", json={"title": "네이버 백엔드"}).json()
    for i, b in enumerate(bodies):
        q = c.post(f"/resumes/{r['id']}/questions", json={"title": f"문항{i}"}).json()
        if b:
            c.post(f"/resumes/{r['id']}/questions/{q['id']}/versions", json={"body": b})
    return r


def _start(c, rid, **kw):
    return c.post(f"/resumes/{rid}/interviews", json=kw)


def _say(c, rid, sid, text="캐시를 도입했습니다."):
    return c.post(f"/resumes/{rid}/interviews/{sid}/answers", json={"answer": text})


# --- 파싱 ---------------------------------------------------------------------

def test_parse_turn_and_feedback():
    assert service.parse_turn("[꼬리]\n역할은?", follow_allowed=True) == ("follow_up", "역할은?")
    assert service.parse_turn("**[다음]** 지원 동기는?", follow_allowed=True) == ("next", "지원 동기는?")
    assert service.parse_turn("역할은?", follow_allowed=True) == ("follow_up", "역할은?"), "표시 없으면 꼬리"
    assert service.parse_turn("[꼬리]\n역할은?", follow_allowed=False) == ("next", "역할은?"), "상한이면 다음"
    fb = service.parse_feedback(
        "### 평가\n**구조:** 좋음\n질문별:\n- Q1: 좋음\n- Q2: 보통\n**개선 제안**: 수치")
    assert fb["구조"] == "좋음" and fb["질문별"] == "- Q1: 좋음\n- Q2: 보통" and fb["제안"] == "수치"
    assert service.parse_questions("1. **가?**\n- 2. `나`?", 5) == ["가?", "나?"]


# --- 시작 ---------------------------------------------------------------------

def test_start_uses_own_material_random_persona_hidden_until_end():
    owner = f"iv-{uuid.uuid4()}"
    g = Script()
    c = _client(owner, g)
    r = _resume(c)
    q0 = c.get(f"/resumes/{r['id']}").json()["questions"][0]
    e = c.post("/experiences", json={"title": "결제 API 개선", "type": "프로젝트"}).json()
    other = c.post("/experiences", json={"title": "연결 안 한 경험", "type": "기타"}).json()
    c.post(f"/resumes/{r['id']}/questions/{q0['id']}/experiences", json={"experience_id": e["id"]})
    res = _start(c, r["id"], main_count=3)
    assert res.status_code == 201, res.text
    s = res.json()["session"]
    assert s["status"] == "active" and s["main_count"] == 3 and s["main_no"] == 1
    assert s["persona"] is None, "진행 중에는 면접관 유형을 알려 주지 않는다"
    assert [(m["role"], m["kind"]) for m in s["messages"]] == [("interviewer", "main")]
    assert s["messages"][0]["body"] == "안녕하세요. 자기소개 부탁드립니다."
    prompt, ctx = g.prompts[0]
    assert ctx.feature == "interview" and ctx.session_id == f"interview-{s['id']}"
    assert "결제 API 응답 시간을 40%" in prompt and "결제 API 개선" in prompt
    assert other["title"] not in prompt, "연결하지 않은 경험은 넣지 않는다"
    with SessionLocal() as db:
        persona = db.get(InterviewSession, uuid.UUID(s["id"])).persona
    assert persona in service.PERSONAS
    label = service.PERSONAS[persona][0]
    assert label in prompt
    _say(c, r["id"], s["id"])
    assert label in g.prompts[-1][0], "같은 면접 동안 페르소나 유지"


def test_start_rejections_and_failures():
    owner = f"iv-{uuid.uuid4()}"
    c = _client(owner, Script())
    r = _resume(c)
    assert _start(c, r["id"], main_count=2).status_code == 422
    assert _start(c, r["id"], main_count=8).status_code == 422
    assert _start(c, _resume(c, bodies=(None,))["id"]).status_code == 422, "본문 없는 자소서"
    assert _start(_client(f"iv-{uuid.uuid4()}", Script()), r["id"]).status_code == 404, "남의 자소서"
    c = _client(owner, Script(unavailable=True))
    out = _start(c, r["id"]).json()
    assert out["session"] is None and out["llm_unavailable"] is True
    c = _client(owner, Script(blocked=True))
    assert _start(c, r["id"]).json()["blocked_reason"] == "INJ-01"
    assert c.get(f"/resumes/{r['id']}/interviews").json() == [], "실패하면 면접을 만들지 않는다"
    sysc = _client(f"iv-{uuid.uuid4()}", Script(), role=Role.SYSTEM)
    assert _start(sysc, r["id"]).status_code == 403


def test_start_with_real_guardrail_pipeline_masks_phone():
    provider = FakeProvider(reply="[다음]\n자기소개 부탁드립니다.")
    c = _client(f"iv-{uuid.uuid4()}", Guardrail(llm=LlmClient(provider=provider), vault=InMemoryVaultStore()))
    r = _resume(c)
    res = _start(c, r["id"])
    assert res.status_code == 201, res.text
    assert PHONE not in provider.calls[0].prompt


# --- 진행 ---------------------------------------------------------------------

def test_follow_up_limit_then_next_main_then_auto_finish_with_feedback():
    owner = f"iv-{uuid.uuid4()}"
    # 모델은 계속 꼬리 질문을 하려 하지만 서버가 주 질문당 2개로 끊는다
    g = Script(turns=["[꼬리]\n근거는?"])
    c = _client(owner, g)
    r = _resume(c)
    s = _start(c, r["id"], main_count=3).json()["session"]
    kinds = []
    for _ in range(12):
        out = _say(c, r["id"], s["id"]).json()["session"]
        kinds.append(out["messages"][-1]["kind"])
        if out["status"] == "finished":
            break
    assert kinds == ["follow_up", "follow_up", "main", "follow_up", "follow_up", "main",
                     "follow_up", "follow_up", "closing"][:len(kinds)]
    assert out["status"] == "finished" and out["messages"][-1]["body"] == service.CLOSING
    assert out["persona_label"] in {v[0] for v in service.PERSONAS.values()}, "끝나면 면접관 유형 공개"
    assert out["feedback"]["구체성"] == "수치가 부족합니다."
    assert "꼬리 질문: 근거 부족" in out["feedback"]["질문별"]
    assert out["expected_questions"] == ["지원 동기는?", "가장 어려웠던 문제는?"]
    assert _say(c, r["id"], s["id"]).status_code == 409, "끝난 면접에는 답할 수 없다"


def test_next_on_last_main_closes_with_model_greeting():
    owner = f"iv-{uuid.uuid4()}"
    g = Script(turns=["[다음]\n두 번째 질문입니다.", "[다음]\n다음 질문입니다.",
                      "[다음]\n오늘 감사했습니다."])
    c = _client(owner, g)
    r = _resume(c)
    s = _start(c, r["id"], main_count=3).json()["session"]
    out = _say(c, r["id"], s["id"]).json()["session"]
    assert out["messages"][-1]["kind"] == "main" and out["main_no"] == 2
    _say(c, r["id"], s["id"])
    out = _say(c, r["id"], s["id"]).json()["session"]
    last = out["messages"][-1]
    assert out["status"] == "finished" and (last["kind"], last["body"]) == ("closing", "오늘 감사했습니다.")
    assert "마무리 인사" in g.prompts[-3][0], "마지막 주 질문에서는 [다음]이 마무리"


def test_answer_sensitive_blocked_unavailable_not_saved_and_ownership():
    owner = f"iv-{uuid.uuid4()}"
    g = Script()
    c = _client(owner, g)
    r = _resume(c)
    s = _start(c, r["id"]).json()["session"]
    n = len(g.prompts)
    res = _say(c, r["id"], s["id"], "제 주민번호는 900101-1234567 입니다")
    assert res.status_code == 422 and len(g.prompts) == n, "민감정보는 모델에 보내기 전에 거부"
    failing = ((Script(blocked=True), "blocked_reason"), (Script(unavailable=True), "llm_unavailable"))
    for guard, key in failing:
        c = _client(owner, guard)
        out = _say(c, r["id"], s["id"]).json()
        assert out[key] and len(out["session"]["messages"]) == 1, "이번 턴 저장 안 함"
    c = _client(owner, Script())
    out = _say(c, r["id"], s["id"], f"연락은 {PHONE}").json()["session"]
    assert PHONE in out["messages"][1]["body"], "본인에게는 원문"
    with SessionLocal() as db:
        row = db.scalars(select(InterviewMessage).where(
            InterviewMessage.session_id == uuid.UUID(s["id"]), InterviewMessage.role == "candidate")).one()
        assert PHONE not in row.body and row.vault_id and row.grade == "personal", "토큰화 저장·개인 등급"
    stranger = _client(f"iv-{uuid.uuid4()}", Script())
    assert _say(stranger, r["id"], s["id"]).status_code == 404
    assert stranger.get(f"/resumes/{r['id']}/interviews/{s['id']}").status_code == 404


# --- 종료·피드백 ------------------------------------------------------------------

def test_user_finish_feedback_and_retry():
    owner = f"iv-{uuid.uuid4()}"
    c = _client(owner, Script())
    r = _resume(c)
    empty = _start(c, r["id"]).json()["session"]
    out = c.post(f"/resumes/{r['id']}/interviews/{empty['id']}/finish").json()["session"]
    assert out["status"] == "finished" and out["feedback"] is None, "답변 없이 끝내면 피드백 없음"
    assert c.post(f"/resumes/{r['id']}/interviews/{empty['id']}/feedback").status_code == 422
    s = _start(c, r["id"]).json()["session"]
    _say(c, r["id"], s["id"])
    c = _client(owner, Script(unavailable=True))
    out = c.post(f"/resumes/{r['id']}/interviews/{s['id']}/finish").json()
    assert out["llm_unavailable"] and out["session"]["status"] == "finished"
    assert out["session"]["feedback"] is None
    c = _client(owner, Script())
    out = c.post(f"/resumes/{r['id']}/interviews/{s['id']}/feedback").json()["session"]
    assert out["feedback"]["제안"] == "결과를 수치로." and len(out["expected_questions"]) == 2
    listed = c.get(f"/resumes/{r['id']}/interviews").json()
    got = {x["id"]: (x["answers"], x["has_feedback"]) for x in listed}
    assert got == {s["id"]: (1, True), empty["id"]: (0, False)}
    active = _start(c, r["id"]).json()["session"]
    assert c.post(f"/resumes/{r['id']}/interviews/{active['id']}/feedback").status_code == 409, "진행 중"


def test_delete_and_purge_drop_vaults():
    from app.features.deletion import service as deletion
    from app.models import PiiVault, Resume

    owner = f"iv-{uuid.uuid4()}"
    c = _client(owner, Script())
    r = _resume(c)
    s = _start(c, r["id"]).json()["session"]
    _say(c, r["id"], s["id"], f"번호 {PHONE}")
    with SessionLocal() as db:
        vaults = set(db.scalars(select(InterviewMessage.vault_id).where(
            InterviewMessage.session_id == uuid.UUID(s["id"]))).all()) - {None}
    assert vaults
    stranger = _client(f"iv-{uuid.uuid4()}", Script())
    assert stranger.delete(f"/resumes/{r['id']}/interviews/{s['id']}").status_code == 404
    c = _client(owner, Script())
    assert c.delete(f"/resumes/{r['id']}/interviews/{s['id']}").status_code == 204
    with SessionLocal() as db:
        assert db.get(InterviewSession, uuid.UUID(s["id"])) is None
        assert all(db.get(PiiVault, v) is None for v in vaults)
    s2 = _start(c, r["id"]).json()["session"]
    _say(c, r["id"], s2["id"], f"번호 {PHONE}")
    with SessionLocal.begin() as db:
        vaults = set(db.scalars(select(InterviewMessage.vault_id).where(
            InterviewMessage.session_id == uuid.UUID(s2["id"]))).all()) - {None}
        deletion.purge_resume(db, db.get(Resume, uuid.UUID(r["id"])))
    with SessionLocal() as db:
        assert all(db.get(PiiVault, v) is None for v in vaults)
