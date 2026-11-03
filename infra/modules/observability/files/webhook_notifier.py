"""D16 — SNS(nesume-<env>-alerts) → Discord 또는 Slack 웹훅. 의존성 없음(urllib).

받는 메시지 두 종류
  1. 앱 알림(app/app/core/alerts.py): JSON {type, severity, summary, ts, session_id?, user_id?, request_id, env}
  2. CloudWatch 알람: JSON {AlarmName, NewStateValue, OldStateValue, NewStateReason, AlarmDescription, StateChangeTime, ...}
웹훅 URL 은 Secrets Manager(앱 시크릿 JSON)의 WEBHOOK_SECRET_KEY 필드. 호출마다 읽지 않고 컨테이너 수명 동안 캐시.
URL 호스트가 slack.com 이면 Slack 형식({text}), 아니면 Discord 임베드(앱의 discord_embed 와 같은 구성:
author 분류 → title 심각도·유형 → 인용 요약 → 필드(세션·사용자·요청, 처리 필요) → footer).
URL 이 비어 있으면 아무것도 보내지 않는다(설정 전 단계) — 실패로 처리하지 않아 SNS 재시도가 쌓이지 않는다.
"""
import json
import os
import re
import urllib.parse
import urllib.request

import boto3

SECRET_ARN = os.environ["SECRET_ARN"]
SECRET_KEY = os.environ.get("WEBHOOK_SECRET_KEY", "ALERTS_WEBHOOK_URL")
ENV = os.environ.get("ENV", "")
USERNAME = os.environ.get("WEBHOOK_USERNAME", "NESUME RADAR")
_cache = {}

COLORS = {"critical": 0xE53935, "warn": 0xF59E0B, "info": 0x3B82F6, "ok": 0x22C55E, "unknown": 0x6B7280}
ICONS = {"critical": "🚨", "warn": "⚠️", "info": "ℹ️"}
SEVERITY_LABELS = {"critical": "긴급", "warn": "주의", "info": "안내"}
TYPE_LABELS = {
    "canary_hit": "카나리 적중", "exfil_threshold": "탈취 세션 제한", "block_spike": "차단 급증",
    "collector_failed": "공고 수집 실패", "alarm": "알람", "session_blocked": "세션 수동 차단",
    "session_released": "세션 차단 해제",
}
CATEGORIES = {
    "canary_hit": "보안 이벤트", "exfil_threshold": "보안 이벤트", "block_spike": "보안 이벤트",
    "collector_failed": "배치", "alarm": "알람", "session_blocked": "운영자 조치", "session_released": "운영자 조치",
}
ACTIONS = {
    "canary_hit": "즉시 운영 대시보드 → 최근 이벤트의 사용자 확인. 원인(검색 필터·매트릭스) 확인 전엔 세션 해제 금지",
    "exfil_threshold": "AI 사용 기록에서 이 세션의 질의 확인. 반복이면 /admin/sessions 에서 해제까지 차단 또는 역할 회수",
    "block_spike": "운영 대시보드 상위 사용자·유형 확인. 특정 세션이면 수동 차단",
    "collector_failed": "대시보드 '배치 결과' 패널 → 파드 로그의 FAILED 소스 확인(API 키 만료·임베더 다운이 흔한 원인)",
    "alarm": "docs/ops/observability.md 3장 '먼저 볼 것'",
    "session_blocked": "기록용. 차단 사유는 /admin/sessions 메모",
    "session_released": "기록용",
}
#: 알람 설명은 "조건. 먼저 볼 것" 꼴로 적혀 있다(observability/main.tf). 마지막 문장을 '처리 필요'로 뽑는다
_ALARM_HINT = re.compile(r"[.。]\s*(?=[^.。]+$)")


def webhook_url():
    if "url" not in _cache:
        raw = boto3.client("secretsmanager").get_secret_value(SecretId=SECRET_ARN)["SecretString"]
        # PowerShell 의 Set-Content -Encoding utf8 이 붙이는 BOM 을 견딘다(11-03 실제 발생)
        _cache["url"] = (json.loads(raw.lstrip("﻿")).get(SECRET_KEY) or "").strip()
    return _cache["url"]


def kind(url):
    host = urllib.parse.urlparse(url).hostname or ""
    return "slack" if host.endswith("slack.com") else "discord"


def parse(message):
    try:
        return json.loads(message)
    except ValueError:
        return None


def quote(text, limit=1800):
    lines = (text or "")[:limit].splitlines() or [""]
    return "\n".join(f"> {line}" for line in lines)


def alarm_embed(body):
    state = body.get("NewStateValue", "")
    old = body.get("OldStateValue", "")
    name = body.get("AlarmName", "")
    short = name.replace(f"nesume-{ENV}-", "")
    icon, label, color = {
        "ALARM": ("🚨", "알람 발생", COLORS["critical"]),
        "OK": ("✅", "복구", COLORS["ok"]),
    }.get(state, ("❔", f"상태 {state}", COLORS["unknown"]))
    description = body.get("AlarmDescription") or ""
    reason = body.get("NewStateReason", "")
    fields = [
        {"name": "🔁 상태", "value": f"`{old or '?'}` → `{state}`", "inline": True},
        {"name": "🕒 시각", "value": (body.get("StateChangeTime") or "")[:19].replace("T", " ") or "-", "inline": True},
    ]
    if reason:
        fields.append({"name": "📊 이유 (CloudWatch)", "value": reason[:900], "inline": False})
    hint = _ALARM_HINT.split(description.strip(), maxsplit=1)
    if state == "ALARM" and len(hint) == 2 and hint[1].strip():
        fields.append({"name": "📌 처리 필요", "value": hint[1].strip(), "inline": False})
    return {
        "author": {"name": "nesume · CloudWatch"},
        "title": f"{icon} {label} · {short}",
        "description": quote(description) if description else None,
        "fields": fields,
        "color": color,
        "footer": {"text": name},
        "timestamp": body.get("StateChangeTime"),
    }


def app_embed(body):
    sev = body.get("severity", "warn")
    typ = body.get("type", "")
    fields = [
        {"name": name, "value": f"`{body[key]}`", "inline": True}
        for name, key in (("🧭 세션", "session_id"), ("👤 사용자", "user_id"), ("🔗 요청", "request_id"))
        if body.get(key)
    ]
    if ACTIONS.get(typ):
        fields.append({"name": "📌 처리 필요", "value": ACTIONS[typ], "inline": False})
    return {
        "author": {"name": f"nesume · {CATEGORIES.get(typ, '알림')}"},
        "title": f"{ICONS.get(sev, '🔔')} {SEVERITY_LABELS.get(sev, sev)} · {TYPE_LABELS.get(typ, typ)}",
        "description": quote(body.get("summary")),
        "fields": fields,
        "color": COLORS.get(sev, COLORS["unknown"]),
        "footer": {"text": typ},
        "timestamp": body.get("ts"),
    }


def discord_embed(subject, message):
    body = parse(message)
    if body is None:
        return {"title": subject or "nesume", "description": quote(message), "color": COLORS["info"]}
    if "AlarmName" in body:
        return alarm_embed(body)
    return app_embed(body)


def slack_text(subject, message):
    body = parse(message)
    if body is None:
        return f"*{subject or 'nesume'}*\n{message[:1500]}"
    if "AlarmName" in body:
        state = body.get("NewStateValue", "")
        return (f"*[nesume-{ENV}] 알람 {state}: {body.get('AlarmName', '')}*\n"
                f"{body.get('AlarmDescription') or ''}\n_{body.get('NewStateReason', '')[:300]}_")
    who = " ".join(f"{k}={body[k]}" for k in ("session_id", "user_id") if body.get(k))
    lines = [f"*[nesume-{body.get('env', ENV)}] {body.get('severity', 'warn').upper()} {body.get('type', '')}*",
             body.get("summary", "")]
    if who:
        lines.append(f"`{who}`")
    return "\n".join(lines)


def payload(url, subject, message):
    if kind(url) == "slack":
        return {"text": slack_text(subject, message)}
    embed = {k: v for k, v in discord_embed(subject, message).items() if v is not None}
    return {"username": USERNAME, "embeds": [embed]}


def handler(event, _context):
    url = webhook_url()
    for record in event.get("Records", []):
        sns = record.get("Sns", {})
        body = payload(url, sns.get("Subject"), sns.get("Message", ""))
        if not url:
            print("webhook url not configured; dropping:", str(body)[:120])
            continue
        req = urllib.request.Request(
            url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "nesume-alerts/1.0"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"webhook HTTP {resp.status}")
    return {"ok": True}
