"""D16 알림 발행(core/alerts.py) — 이벤트 스키마, 기록 줄, 발송 실패 격리, C13 보안 로그 다리.

DB·네트워크 없음.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.core import alerts as alerts_mod
from app.core.alerts import (
    AlertEvent,
    Alerts,
    SecurityLogBridge,
    SnsTransport,
    Transport,
    WebhookTransport,
    build_transport,
)
from app.core.logging import JsonFormatter


class Recorder(Transport):
    name = "rec"

    def __init__(self, fail: bool = False) -> None:
        self.events: list[AlertEvent] = []
        self.fail = fail

    def send(self, event: AlertEvent) -> None:
        if self.fail:
            raise RuntimeError("boom")
        self.events.append(event)


def test_event_schema_and_defaults():
    e = AlertEvent(type="canary_hit", severity="critical", summary="x" * 400, session_id="s", user_id="u")
    assert len(e.summary) == 300
    d = e.to_dict()
    assert d["type"] == "canary_hit" and d["session_id"] == "s" and "env" not in d  # 빈 값은 뺀다
    assert e.subject().startswith("[nesume] CRITICAL canary_hit")
    assert "session=s user=u" in e.chat_text()
    assert e.chat_text().startswith("**[nesume] CRITICAL canary_hit**")
    assert e.chat_text(bold="*").startswith("*[nesume] CRITICAL canary_hit*")


def test_unknown_event_type_rejected():
    with pytest.raises(ValueError):
        AlertEvent(type="nope", severity="warn", summary="x")


class _Collect(logging.Handler):
    """로거에 직접 붙여 레코드를 모은다. 앱의 setup_logging 이 루트 핸들러를 갈아 끼워도 영향이 없다."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        self.records.append(record)


@pytest.fixture
def collect():
    def attach(name: str) -> _Collect:
        handler = _Collect()
        logger = logging.getLogger(name)
        # 전체 스위트에서는 다른 테스트가 루트 레벨·logging.disable 을 바꿔 둘 수 있다 → 이 로거만 강제로 연다
        attached.append((logger, handler, logger.level))
        logger.setLevel(logging.DEBUG)
        logger.disabled = False  # alembic env.py 의 fileConfig 가 기존 로거를 disabled=True 로 만든다
        logger.addHandler(handler)
        return handler

    attached: list[tuple[logging.Logger, _Collect, int]] = []
    previous_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    yield attach
    for logger, handler, level in attached:
        logger.removeHandler(handler)
        logger.setLevel(level)
    logging.disable(previous_disable)


def test_emit_writes_audit_line_and_delivers(collect):
    audit = collect("nesume.audit.alerts")
    rec = Recorder()
    pub = Alerts(rec, sync=True)
    event = pub.emit("exfil_threshold", "탈취 임계치", session_id="sess-1", user_id="u-1")
    assert rec.events == [event]
    assert event.severity == "warn"  # 기본 심각도
    record = next(r for r in audit.records if r.name == "nesume.audit.alerts")
    line = json.loads(JsonFormatter().format(record))
    assert line["log_type"] == "audit" and line["msg"] == "alert"
    assert line["event_type"] == "exfil_threshold" and line["session_id"] == "sess-1"


def test_delivery_failure_is_swallowed(collect):
    app_log = collect("nesume.alerts")
    pub = Alerts(Recorder(fail=True), sync=True)
    pub.emit("canary_hit", "x")  # 예외가 올라오지 않는다
    assert any("alert delivery failed" in r.getMessage() for r in app_log.records)
    assert pub.sent[-1].type == "canary_hit"


def test_log_only_when_no_transport():
    pub = Alerts(None, sync=True)
    pub.emit("alarm", "x")
    assert pub.sent[-1].type == "alarm"


def test_security_bridge_turns_c13_log_into_alert():
    rec = Recorder()
    pub = Alerts(rec, sync=True)
    logger = logging.getLogger("nesume.security.test_bridge")
    bridge = SecurityLogBridge(pub)
    logger.addHandler(bridge)
    try:
        logger.warning("security_event=%s where=%s role=%s user=%s rows=%d token_prefix=%s",
                       "canary_hit", "search_personal", "user", "u1", 1, "ab12")
        logger.warning("unrelated warning")
    finally:
        logger.removeHandler(bridge)
    assert [e.type for e in rec.events] == ["canary_hit"]
    assert rec.events[0].severity == "critical" and "검색 단계 카나리 적중" in rec.events[0].summary


def test_install_bridge_is_idempotent():
    target = logging.getLogger("nesume.security")
    before = [h for h in target.handlers if isinstance(h, SecurityLogBridge)]
    alerts_mod.install_security_bridge()
    alerts_mod.install_security_bridge()
    after = [h for h in target.handlers if isinstance(h, SecurityLogBridge)]
    assert len(after) == 1
    for h in after:
        if h not in before:
            target.removeHandler(h)


class _S:
    alerts_sns_topic_arn = ""
    alerts_webhook_url = ""
    alerts_timeout_s = 2.0
    aws_region = "ap-northeast-2"


def test_build_transport_prefers_sns_then_webhook():
    assert build_transport(_S()) is None
    s = _S()
    s.alerts_webhook_url = "https://discord.com/api/webhooks/1/x"
    assert isinstance(build_transport(s), WebhookTransport)
    s.alerts_sns_topic_arn = "arn:aws:sns:ap-northeast-2:123456789012:nesume-dev-alerts"
    assert isinstance(build_transport(s), SnsTransport)


def test_webhook_must_be_https():
    with pytest.raises(ValueError):
        WebhookTransport("http://discord.com/api/webhooks/1/x", timeout_s=1)


def test_webhook_payload_by_host():
    from app.core.alerts import webhook_kind, webhook_payload

    e = AlertEvent(type="alarm", severity="warn", summary="x")
    discord = "https://discord.com/api/webhooks/1/x"
    slack = "https://hooks.slack.com/services/x"
    assert webhook_kind(discord) == "discord" and webhook_kind(slack) == "slack"
    d = webhook_payload(discord, e)
    assert set(d) == {"username", "embeds"} and d["username"] == "NESUME RADAR"
    embed = d["embeds"][0]
    assert embed["title"] == "⚠️ 주의 · 알람" and embed["color"] == 0xF59E0B and embed["description"] == "> x"
    assert embed["author"]["name"] == "nesume · ? · 알람"
    rich = webhook_payload(discord, AlertEvent(type="canary_hit", severity="critical", summary="s",
                                               session_id="sess", user_id="u", env="dev"))["embeds"][0]
    assert rich["color"] == 0xE53935 and rich["title"] == "🚨 긴급 · 카나리 적중"
    assert rich["author"]["name"] == "nesume · dev · 보안 이벤트"
    names = [f["name"] for f in rich["fields"]]
    assert names[:2] == ["🧭 세션", "👤 사용자"] and names[-1] == "📌 바로 할 일"
    assert rich["fields"][-1]["inline"] is False
    assert rich["footer"]["text"] == "canary_hit · D16"
    assert set(webhook_payload(slack, e)) == {"text"} and "*[nesume]" in webhook_payload(slack, e)["text"]
    assert WebhookTransport(discord, timeout_s=1).name == "discord"


def test_cli_emits_without_transport(capsys):
    assert alerts_mod.main(["collector_failed", "seoul: FAILED"]) == 0
