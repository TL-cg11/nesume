"""D16 — SNS(nesume-<env>-alerts) → Discord 또는 Slack 웹훅. 의존성 없음(urllib).

받는 메시지 두 종류
  1. 앱 알림(app/app/core/alerts.py): JSON {type, severity, summary, ts, session_id?, user_id?, request_id, env}
  2. CloudWatch 알람: JSON {AlarmName, NewStateValue, NewStateReason, AlarmDescription, ...}
웹훅 URL 은 Secrets Manager(앱 시크릿 JSON)의 WEBHOOK_SECRET_KEY 필드. 호출마다 읽지 않고 컨테이너 수명 동안 캐시.
URL 호스트가 slack.com 이면 Slack 형식({text}), 아니면 Discord 임베드(심각도 색 막대·필드·시각, 앱의 discord_embed 와 같은 모양).
URL 이 비어 있으면 아무것도 보내지 않는다(설정 전 단계) — 실패로 처리하지 않아 SNS 재시도가 쌓이지 않는다.
"""
import json
import os
import urllib.parse
import urllib.request

import boto3

SECRET_ARN = os.environ["SECRET_ARN"]
SECRET_KEY = os.environ.get("WEBHOOK_SECRET_KEY", "ALERTS_WEBHOOK_URL")
ENV = os.environ.get("ENV", "")
USERNAME = os.environ.get("WEBHOOK_USERNAME", "네슘 파수꾼")
_cache = {}

COLORS = {"critical": 0xE53935, "warn": 0xF59E0B, "info": 0x3B82F6, "ok": 0x22C55E}
ICONS = {"critical": "🚨", "warn": "⚠️", "info": "ℹ️"}
TYPE_LABELS = {
    "canary_hit": "카나리 적중", "exfil_threshold": "탈취 세션 제한", "block_spike": "차단 급증",
    "collector_failed": "공고 수집 실패", "alarm": "알람", "session_blocked": "세션 수동 차단",
    "session_released": "세션 차단 해제",
}


def webhook_url():
    if "url" not in _cache:
        raw = boto3.client("secretsmanager").get_secret_value(SecretId=SECRET_ARN)["SecretString"]
        _cache["url"] = (json.loads(raw).get(SECRET_KEY) or "").strip()
    return _cache["url"]


def kind(url):
    host = urllib.parse.urlparse(url).hostname or ""
    return "slack" if host.endswith("slack.com") else "discord"


def parse(message):
    try:
        return json.loads(message)
    except ValueError:
        return None


def discord_embed(subject, message):
    body = parse(message)
    if body is None:
        return {"title": subject or "nesume", "description": message[:1900], "color": COLORS["info"]}
    if "AlarmName" in body:  # CloudWatch 알람
        state = body.get("NewStateValue", "")
        icon, color = {"ALARM": ("🚨", COLORS["critical"]), "OK": ("✅", COLORS["ok"])}.get(state, ("❔", 0x6B7280))
        return {
            "title": f"{icon} 알람 {state}: {body.get('AlarmName', '')}",
            "description": (body.get("AlarmDescription") or "")[:1900],
            "fields": [{"name": "이유", "value": body.get("NewStateReason", "")[:900] or "-", "inline": False}],
            "color": color,
            "footer": {"text": f"nesume-{ENV} · CloudWatch"},
            "timestamp": body.get("StateChangeTime"),
        }
    sev = body.get("severity", "warn")
    fields = [
        {"name": name, "value": f"`{body[key]}`", "inline": True}
        for name, key in (("세션", "session_id"), ("사용자", "user_id"), ("요청", "request_id"))
        if body.get(key)
    ]
    return {
        "title": f"{ICONS.get(sev, '🔔')} {TYPE_LABELS.get(body.get('type'), body.get('type', ''))}",
        "description": (body.get("summary") or "")[:1900],
        "fields": fields,
        "color": COLORS.get(sev, 0x6B7280),
        "footer": {"text": f"nesume-{body.get('env', ENV)} · {sev} · {body.get('type', '')}"},
        "timestamp": body.get("ts"),
    }


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
