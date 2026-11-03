"""D16 — 알림 이벤트 발행 (docs/ops/alerts.md).

보안·운영 이벤트를 **한 함수** `emit()` 으로 내보낸다. 받는 쪽은 둘이다.

    1. 감사 로그 스트림: `nesume.audit.alerts` 로거(log_type=audit → CloudWatch /nesume/<env>/audit).
       무엇이 언제 왔는지의 기록. 발송이 실패해도 이 줄은 남는다.
    2. 발송: SNS 토픽 Publish(ALERTS_SNS_TOPIC_ARN, IRSA sns:Publish) → 이메일 구독 + Slack Lambda
       (infra/modules/observability). 토픽이 없고 ALERTS_SLACK_WEBHOOK_URL 만 있으면(로컬·kind) 웹훅에
       직접 POST.
       둘 다 없으면 1번만 남는다(테스트 기본).

★ 요청 처리에 영향을 주지 않는다. 발송은 백그라운드 스레드에서 하고(타임아웃 2s), 어떤 예외도 삼킨다.
  알림이 안 가는 것과 사용자 요청이 죽는 것 중 전자가 낫다 — 기록(1번)은 어차피 남는다.
★ 본문에 질의 원문·PII·토큰 전체를 넣지 않는다. `summary` 는 호출자가 이미 가린 한 줄이다.

호출하는 곳
    - core/session_block.py: 카나리 적중(canary_hit)·탈취 임계치(exfil_threshold) → 세션 자동 차단과 함께
    - 운영자 API(auth/admin_sessions.py): 수동 차단·해제(session_blocked / session_released)
    - retrieval/canary.report 의 `nesume.security` 로그 → `SecurityLogBridge` 가 받아 canary_hit 로 (C
    코드 수정 없이)
    - C4 수집 배치: `python -m app.core.alerts collector_failed "<요약>"` 또는 emit() 직접 호출(C 담당).
      CloudWatch 쪽에서는 jobs-collector 파드 로그의 FAILED 를 3일 연속 세는 알람이 따로 있다.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Literal

from app.core.context import get_request_id

log = logging.getLogger("nesume.alerts")
audit_log = logging.getLogger("nesume.audit.alerts")

EventType = Literal[
    "canary_hit",        # 카나리 미끼가 검색 결과·응답에 섞임 (C13·A5)
    "exfil_threshold",   # 탈취 세션 제한 임계치 도달 (C7, 5회/10분)
    "block_spike",       # 차단 급증 (CloudWatch 알람이 주로 만든다)
    "collector_failed",  # 공고 수집 실패 (C4)
    "alarm",             # 기타 CloudWatch 알람·수동 알림
    "session_blocked",   # 운영자 수동 차단
    "session_released",  # 운영자 차단 해제
]
EVENT_TYPES: tuple[str, ...] = EventType.__args__  # type: ignore[attr-defined]
Severity = Literal["info", "warn", "critical"]

#: 이벤트별 기본 심각도. 카나리는 필터가 뚫렸다는 뜻이라 항상 critical.
DEFAULT_SEVERITY: dict[str, str] = {
    "canary_hit": "critical",
    "exfil_threshold": "warn",
    "block_spike": "warn",
    "collector_failed": "warn",
    "alarm": "warn",
    "session_blocked": "info",
    "session_released": "info",
}

SUMMARY_MAX = 300


@dataclass(frozen=True)
class AlertEvent:
    """알림 한 건. 스키마는 docs/ops/alerts.md 2장과 같다."""

    type: str
    severity: str
    summary: str
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    request_id: str = ""
    session_id: str | None = None
    user_id: str | None = None
    env: str = ""

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"알 수 없는 이벤트 유형: {self.type!r}")
        if len(self.summary) > SUMMARY_MAX:
            object.__setattr__(self, "summary", self.summary[:SUMMARY_MAX])

    def to_dict(self) -> dict[str, object]:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}

    def subject(self) -> str:
        """SNS 제목(100자 제한)·Slack 첫 줄."""
        return f"[nesume{('-' + self.env) if self.env else ''}] {self.severity.upper()} {self.type}"[:100]

    def slack_text(self) -> str:
        who = " ".join(
            f"{k}={v}" for k, v in (("session", self.session_id), ("user", self.user_id)) if v
        )
        return f"*{self.subject()}*\n{self.summary}" + (f"\n`{who}`" if who else "") + f"\n{self.ts}"


# --------------------------------------------------------------------------
# 발송 경로
# --------------------------------------------------------------------------

class Transport:
    """발송 한 경로. 동기 함수라 스레드에서 돈다. 실패는 예외로 올리고 `_deliver` 가 로그만 남긴다."""

    name = "none"

    def send(self, event: AlertEvent) -> None:  # pragma: no cover - 인터페이스
        raise NotImplementedError


class SnsTransport(Transport):
    name = "sns"

    def __init__(self, topic_arn: str, *, region: str | None, timeout_s: float) -> None:
        import boto3
        from botocore.config import Config

        self._arn = topic_arn
        # 엔드포인트를 명시하지 않는다 — 로컬(LocalStack)은 AWS_ENDPOINT_URL 로 자연히 간다
        from app.config import get_settings

        self._client = boto3.client(
            "sns",
            region_name=region or topic_arn.split(":")[3],
            endpoint_url=get_settings().aws_endpoint_url,
            config=Config(connect_timeout=timeout_s, read_timeout=timeout_s, retries={"max_attempts": 1}),
        )

    def send(self, event: AlertEvent) -> None:
        self._client.publish(
            TopicArn=self._arn,
            Subject=event.subject(),
            Message=json.dumps(event.to_dict(), ensure_ascii=False),
            MessageAttributes={
                "type": {"DataType": "String", "StringValue": event.type},
                "severity": {"DataType": "String", "StringValue": event.severity},
            },
        )


class SlackWebhookTransport(Transport):
    name = "slack"

    def __init__(self, url: str, *, timeout_s: float) -> None:
        if not url.startswith("https://"):
            raise ValueError("Slack 웹훅 URL 은 https 여야 합니다")
        self._url = url
        self._timeout = timeout_s

    def send(self, event: AlertEvent) -> None:
        body = json.dumps({"text": event.slack_text()}).encode("utf-8")
        req = urllib.request.Request(
            self._url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310 - https 만 허용
            if resp.status >= 300:
                raise RuntimeError(f"Slack webhook HTTP {resp.status}")


def build_transport(settings) -> Transport | None:
    """설정으로 발송 경로를 고른다. SNS 가 있으면 SNS(Slack 은 토픽 구독 Lambda 가 맡는다), 없으면 웹훅."""
    if settings.alerts_sns_topic_arn:
        return SnsTransport(
            settings.alerts_sns_topic_arn, region=settings.aws_region, timeout_s=settings.alerts_timeout_s
        )
    if settings.alerts_slack_webhook_url:
        return SlackWebhookTransport(settings.alerts_slack_webhook_url, timeout_s=settings.alerts_timeout_s)
    return None


# --------------------------------------------------------------------------
# 발행
# --------------------------------------------------------------------------

class Alerts:
    """발행기. 앱에 하나(`alerts`). 테스트는 `transport` 를 갈아 끼우거나 `sync=True` 로 만든다."""

    def __init__(self, transport: Transport | None = None, *, sync: bool = False) -> None:
        self._transport = transport
        self._configured = transport is not None
        self._sync = sync
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="alerts")
        self._lock = threading.Lock()
        self.sent: list[AlertEvent] = []  # 테스트·진단용(최근 50건)

    def configure(self, transport: Transport | None) -> None:
        self._transport = transport
        self._configured = True

    def _ensure(self) -> Transport | None:
        if not self._configured:
            from app.config import get_settings

            try:
                self.configure(build_transport(get_settings()))
            except Exception:  # noqa: BLE001 - 설정 오류로 앱이 죽지 않게. 로그만
                log.warning("alert transport misconfigured, alerts will be log-only", exc_info=True)
                self.configure(None)
        return self._transport

    def emit(
        self,
        event_type: str,
        summary: str,
        *,
        severity: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> AlertEvent:
        from app.config import get_settings

        event = AlertEvent(
            type=event_type,
            severity=severity or DEFAULT_SEVERITY.get(event_type, "warn"),
            summary=summary,
            request_id=request_id or get_request_id() or "",
            session_id=session_id or None,
            user_id=user_id or None,
            env=get_settings().app_env,
        )
        # 1. 기록 — 발송과 무관하게 항상
        audit_log.log(
            logging.CRITICAL if event.severity == "critical" else logging.WARNING,
            "alert",
            extra={"fields": {"event_type": event.type, "severity": event.severity, "summary": event.summary,
                              "session_id": event.session_id, "alert_user_id": event.user_id}},
        )
        with self._lock:
            self.sent.append(event)
            del self.sent[:-50]
        # 2. 발송 — 백그라운드
        if self._sync:
            self._deliver(event)
        else:
            try:
                self._pool.submit(self._deliver, event)
            except RuntimeError:  # 인터프리터 종료 중
                pass
        return event

    def _deliver(self, event: AlertEvent) -> None:
        transport = self._ensure()
        if transport is None:
            return
        try:
            transport.send(event)
        except Exception:  # noqa: BLE001 - 발송 실패가 요청을 깨면 안 된다
            log.warning("alert delivery failed", extra={"fields": {"transport": transport.name,
                                                                   "event_type": event.type}}, exc_info=True)


alerts = Alerts()


def emit(event_type: str, summary: str, **kw) -> AlertEvent:
    """모듈 함수 형태. `alerts.emit` 과 같다."""
    return alerts.emit(event_type, summary, **kw)


# --------------------------------------------------------------------------
# C13 보안 로그 → 이벤트 다리
# --------------------------------------------------------------------------

_SECURITY_EVENT = re.compile(r"security_event=(canary_hit|filter_bypass)\b")


class SecurityLogBridge(logging.Handler):
    """`nesume.security` 로거의 `security_event=…` 줄을 알림으로 바꾼다.

    C13(`retrieval/canary.report`)은 세션을 모르고 로그만 남긴다. 그 코드를 고치지 않고도 검색 단계 카나리를
    Slack 으로 받기 위해 로거에 핸들러를 하나 건다. 세션 ID 가 없으므로 자동 차단은 하지 않는다 —
    차단은 응답 단계(세션을 아는 session_block 래퍼)가 맡는다. A8 이 검색 판정을 합치면(블록 정책 11장)
    그쪽도 래퍼가 본다.
    """

    def __init__(self, publisher: Alerts | None = None) -> None:
        super().__init__(level=logging.WARNING)
        self._publisher = publisher

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102 - logging.Handler 규약
        try:
            msg = record.getMessage()
            m = _SECURITY_EVENT.search(msg)
            if not m:
                return
            kind = m.group(1)
            (self._publisher or alerts).emit(
                "canary_hit",
                f"검색 단계 {'카나리 적중' if kind == 'canary_hit' else '권한 필터 우회'}: {msg[:200]}",
                severity="critical",
            )
        except Exception:  # noqa: BLE001 - 핸들러 오류가 원래 로그를 막지 않게
            self.handleError(record)


def install_security_bridge() -> None:
    """앱 기동 시 한 번(main.create_app). 두 번 불려도 핸들러는 하나다."""
    target = logging.getLogger("nesume.security")
    if not any(isinstance(h, SecurityLogBridge) for h in target.handlers):
        target.addHandler(SecurityLogBridge())


# --------------------------------------------------------------------------
# CLI: python -m app.core.alerts collector_failed "seoul: FAILED 3회"
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D16 알림 발행(배치·수동용)")
    parser.add_argument("type", choices=EVENT_TYPES)
    parser.add_argument("summary")
    parser.add_argument("--severity", choices=("info", "warn", "critical"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    publisher = Alerts(sync=True)
    publisher.emit(args.type, args.summary, severity=args.severity)
    return 0


if __name__ == "__main__":
    sys.exit(main())
