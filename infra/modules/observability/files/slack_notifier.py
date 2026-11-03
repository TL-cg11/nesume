"""D16 — SNS(nesume-<env>-alerts) → Slack Incoming Webhook. 의존성 없음(urllib).

받는 메시지 두 종류
  1. 앱 알림(app/app/core/alerts.py): JSON {type, severity, summary, ts, session_id?, user_id?, request_id, env}
  2. CloudWatch 알람: JSON {AlarmName, NewStateValue, NewStateReason, AlarmDescription, ...}
웹훅 URL 은 Secrets Manager(앱 시크릿 JSON)의 WEBHOOK_SECRET_KEY 필드. 호출마다 읽지 않고 컨테이너 수명 동안 캐시.
URL 이 비어 있으면 아무것도 보내지 않는다(설정 전 단계) — 실패로 처리하지 않아 SNS 재시도가 쌓이지 않는다.
"""
import json
import os
import urllib.request

import boto3

SECRET_ARN = os.environ["SECRET_ARN"]
SECRET_KEY = os.environ.get("WEBHOOK_SECRET_KEY", "ALERTS_SLACK_WEBHOOK_URL")
ENV = os.environ.get("ENV", "")
_cache = {}


def webhook_url():
    if "url" not in _cache:
        raw = boto3.client("secretsmanager").get_secret_value(SecretId=SECRET_ARN)["SecretString"]
        _cache["url"] = (json.loads(raw).get(SECRET_KEY) or "").strip()
    return _cache["url"]


ICON = {"critical": ":rotating_light:", "warn": ":warning:", "info": ":information_source:"}


def render(subject, message):
    try:
        body = json.loads(message)
    except ValueError:
        return f"*{subject or 'nesume'}*\n{message[:1500]}"
    if "AlarmName" in body:  # CloudWatch 알람
        state = body.get("NewStateValue", "")
        icon = ":rotating_light:" if state == "ALARM" else ":white_check_mark:" if state == "OK" else ":grey_question:"
        return (
            f"{icon} *[nesume-{ENV}] 알람 {state}: {body.get('AlarmName', '')}*\n"
            f"{body.get('AlarmDescription') or ''}\n_{body.get('NewStateReason', '')[:300]}_"
        )
    sev = body.get("severity", "warn")
    who = " ".join(f"{k}={body[k]}" for k in ("session_id", "user_id") if body.get(k))
    lines = [f"{ICON.get(sev, ':bell:')} *[nesume-{body.get('env', ENV)}] {sev.upper()} {body.get('type', '')}*",
             body.get("summary", "")]
    if who:
        lines.append(f"`{who}`")
    if body.get("request_id"):
        lines.append(f"request_id `{body['request_id']}`")
    return "\n".join(lines)


def handler(event, _context):
    url = webhook_url()
    for record in event.get("Records", []):
        sns = record.get("Sns", {})
        text = render(sns.get("Subject"), sns.get("Message", ""))
        if not url:
            print("webhook url not configured; dropping:", text[:120])
            continue
        req = urllib.request.Request(
            url, data=json.dumps({"text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"slack webhook HTTP {resp.status}")
    return {"ok": True}
