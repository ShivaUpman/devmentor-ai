"""
core/logging.py — Structured JSON logging

WHY structured logging over print() or Python's logging.basicConfig()?

  print("User logged in") produces:
    User logged in

  A structured log produces:
    {
      "timestamp": "2024-01-15T14:23:01.234Z",
      "level": "INFO",
      "event": "user.login",
      "request_id": "a3f9d12b-...",
      "user_id": "550e8400-...",
      "email": "ada@example.com",
      "duration_ms": 45.2,
      "service": "devmentor-backend"
    }

  The second version can be:
    - Searched: find all logins in the last hour
    - Aggregated: count logins per user per day
    - Alerted on: email "admin@competitor.com" logged in (anomaly detection)
    - Correlated: join with request_id to see everything that happened in one request

  This is what Datadog, Splunk, CloudWatch, and Grafana Loki consume.
  JSON logs → log aggregator → dashboards, alerts, anomaly detection.

WHY structlog over Python's built-in logging?
  Python's logging module is excellent but produces unstructured text by default.
  Configuring it for JSON output requires 50+ lines of boilerplate.
  structlog is purpose-built for structured logging:
    - Immutable context binding (add request_id once, it appears in all logs)
    - Processor pipeline (add timestamp, level, service name automatically)
    - First-class async support
    - Testing support (capture log output in tests)

Interview question: "How do you correlate logs across microservices?"
  Inject a trace ID (request_id) at the edge (Nginx/API gateway).
  Propagate it in every downstream HTTP call via a header (X-Request-ID).
  Include it in every log line for every service.
  Now you can filter logs from all services by one trace ID and see
  the complete journey of a single request across the entire system.
"""

import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

# ── Context variable for request-scoped data ───────────────────────────────────
# WHY ContextVar?
#   In async Python, multiple requests are processed concurrently in the same
#   thread. A global variable would mix data from different requests.
#   ContextVar is request-scoped — each async task has its own isolated value.
#   Setting request_id_var in middleware makes it available everywhere in
#   that request's execution without passing it as a parameter.
#
#   asyncio equivalent of thread-local storage.
request_id_var: ContextVar[str] = ContextVar('request_id', default='')
user_id_var: ContextVar[str] = ContextVar('user_id', default='')


def get_request_id() -> str:
    """Get the current request's ID from context."""
    return request_id_var.get() or str(uuid.uuid4())


def set_request_context(request_id: str, user_id: str = '') -> None:
    """Set request-scoped context (called once per request in middleware)."""
    request_id_var.set(request_id)
    if user_id:
        user_id_var.set(user_id)


class StructuredLogger:
    """
    Minimal structured logger that outputs JSON lines to stdout.

    WHY stdout and not a file?
      Containers are ephemeral — their filesystems vanish on restart.
      stdout → Docker logs → log aggregator is the 12-Factor App pattern.
      'docker logs container_name' gives you all logs.
      'docker compose logs -f backend' follows in real-time.
      CloudWatch, Datadog, and Grafana all capture stdout natively.

    Log levels:
      DEBUG:   detailed diagnostic info (disabled in production)
      INFO:    normal operational events (user login, session start)
      WARNING: unexpected but recoverable (cache miss, retry)
      ERROR:   operation failed, needs attention (DB query failed)
      CRITICAL: system cannot function (can't connect to DB at startup)
    """

    SERVICE_NAME = "devmentor-backend"

    def _emit(self, level: str, event: str, **kwargs: Any) -> None:
        """Build and write one structured log line."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event": event,
            "service": self.SERVICE_NAME,
            "request_id": request_id_var.get() or None,
            "user_id": user_id_var.get() or None,
            **kwargs,
        }
        # Remove None values to keep logs compact
        record = {k: v for k, v in record.items() if v is not None}

        # Write as JSON line — each log entry is one line of valid JSON
        # WHY one line? Log aggregators split on newlines. Multi-line JSON
        # would be parsed as multiple broken entries.
        import json
        print(json.dumps(record, default=str), file=sys.stdout, flush=True)
        # flush=True: don't buffer — logs appear immediately even under load

    def debug(self, event: str, **kwargs: Any) -> None:
        self._emit("DEBUG", event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._emit("INFO", event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._emit("WARNING", event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._emit("ERROR", event, **kwargs)

    def critical(self, event: str, **kwargs: Any) -> None:
        self._emit("CRITICAL", event, **kwargs)

    def bind(self, **kwargs: Any) -> 'BoundLogger':
        """
        Return a logger with pre-bound context fields.

        Usage:
          log = logger.bind(session_id=session.id, topic="DSA")
          log.info("session.started")  # includes session_id and topic
          log.info("session.ended")    # includes session_id and topic

        WHY bind?
          Avoids repeating the same context fields in every log call.
          Builds a contextual "sub-logger" for a specific operation.
          Pattern used in structlog, zerolog (Go), and Rust's tracing crate.
        """
        return BoundLogger(self, kwargs)


class BoundLogger:
    """A logger with pre-bound context fields."""

    def __init__(self, parent: StructuredLogger, context: dict[str, Any]):
        self._parent = parent
        self._context = context

    def info(self, event: str, **kwargs: Any) -> None:
        self._parent.info(event, **{**self._context, **kwargs})

    def warning(self, event: str, **kwargs: Any) -> None:
        self._parent.warning(event, **{**self._context, **kwargs})

    def error(self, event: str, **kwargs: Any) -> None:
        self._parent.error(event, **{**self._context, **kwargs})

    def debug(self, event: str, **kwargs: Any) -> None:
        self._parent.debug(event, **{**self._context, **kwargs})

    def bind(self, **kwargs: Any) -> 'BoundLogger':
        """Compose bound loggers — add more context on top of existing."""
        return BoundLogger(self._parent, {**self._context, **kwargs})


# Module-level singleton — import and use anywhere
logger = StructuredLogger()


def configure_stdlib_logging() -> None:
    """
    Redirect Python's stdlib logging (used by SQLAlchemy, uvicorn, etc.)
    to our structured logger so all logs are in the same format.

    WHY redirect stdlib?
      SQLAlchemy logs SQL queries via Python's logging module.
      uvicorn logs startup messages via Python's logging module.
      Without this, you'd have two formats: our JSON + their plaintext.
      Redirecting gives you one consistent format for all log sources.
    """
    class StructuredHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            level_map = {
                logging.DEBUG: 'DEBUG',
                logging.INFO: 'INFO',
                logging.WARNING: 'WARNING',
                logging.ERROR: 'ERROR',
                logging.CRITICAL: 'CRITICAL',
            }
            level = level_map.get(record.levelno, 'INFO')
            logger._emit(
                level,
                record.getMessage(),
                logger_name=record.name,
                exc_info=str(record.exc_info) if record.exc_info else None,
            )

    root_logger = logging.getLogger()
    root_logger.addHandler(StructuredHandler())
    root_logger.setLevel(logging.INFO)

    # Silence noisy libraries at WARNING level
    for noisy in ['sqlalchemy.engine', 'asyncio', 'multipart']:
        logging.getLogger(noisy).setLevel(logging.WARNING)
