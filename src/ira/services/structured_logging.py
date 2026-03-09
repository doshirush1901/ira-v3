"""Structured logging helpers for v4 observability."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone


trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")
span_id_var: ContextVar[str] = ContextVar("span_id", default="-")


class StructuredJsonFormatter(logging.Formatter):
    """Emit machine-parsable JSON logs with request/trace identifiers."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "trace_id": trace_id_var.get("-"),
            "span_id": span_id_var.get("-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def configure_root_logging(log_level: str, log_format: str = "text") -> None:
    """Configure root logging with either text or JSON formatting."""
    resolved_level = getattr(logging, log_level.upper(), logging.INFO)
    if log_format.lower() == "json":
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredJsonFormatter())
        logging.basicConfig(level=resolved_level, handlers=[handler], force=True)
        return
    logging.basicConfig(
        level=resolved_level,
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  [%(request_id)s]  %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
