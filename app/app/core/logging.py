"""구조화 로깅.

- json(기본, 운영): 한 줄 JSON. CloudWatch Logs(D14)에서 필드로 조회 가능.
- text(로컬): 사람이 읽기 쉬운 형식.
모든 줄에 request_id가 붙는다. 로거는 logging.getLogger("nesume.<모듈>") 규칙을 쓴다.
추가 필드는 extra={"fields": {...}}로 넘긴다. 질의 원문·PII는 로그에 넣지 않는다.
"""
import json
import logging
import sys
from datetime import UTC, datetime

from app.core.context import get_request_id


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": get_request_id(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.levelname:5} [{record.name}] rid={get_request_id()} {record.getMessage()}"
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict) and fields:
            base += " " + " ".join(f"{k}={v}" for k, v in fields.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # uvicorn 로거도 같은 형식으로. 접근 로그는 RequestIdMiddleware가 대신 남기므로 끈다.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
