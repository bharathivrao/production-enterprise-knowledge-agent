"""Small, content-safe JSON logging context and process metrics."""

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging

from prometheus_client import Counter, Histogram, generate_latest


request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
REQUESTS = Counter(
    "knowledge_agent_http_requests_total",
    "HTTP requests handled by the API",
    ("method", "route", "status"),
)
REQUEST_DURATION = Histogram(
    "knowledge_agent_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ("method", "route"),
)
WORKFLOW_EVENTS = Counter(
    "knowledge_agent_workflow_events_total",
    "Workflow states and tool outcomes observed by the API",
    ("state", "tool_status"),
)


class SafeJSONFormatter(logging.Formatter):
    """Emit message templates and allowlisted metadata, without traceback text."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.msg if isinstance(record.msg, str) else "log_event",
            "request_id": request_id_var.get(),
        }
        for key in (
            "request_method", "request_path", "status_code", "duration_ms",
            "action", "decision", "subject_hash", "tenant",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        handler = logging.StreamHandler()
        root.addHandler(handler)
    for handler in root.handlers:
        handler.setFormatter(SafeJSONFormatter())


def metrics_payload() -> bytes:
    return generate_latest()


def record_workflow_trace(events) -> None:
    for event in events:
        state = getattr(event, "state", "unknown")
        status = getattr(event, "tool_status", None) or "none"
        if status not in {"success", "error", "timeout", "not_found", "denied", "none"}:
            status = "other"
        WORKFLOW_EVENTS.labels(str(state), status).inc()
