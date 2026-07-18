"""Structured logging configuration for PxeOS."""

from __future__ import annotations

import json
import logging
import sys
from typing import Optional


class JsonFormatter(logging.Formatter):
    """Format log records as JSON lines for log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(
                record.exc_info
            )
        if hasattr(record, "extra_data"):
            log_entry["extra"] = record.extra_data
        return json.dumps(log_entry, default=str)


_DEFAULT_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s %(message)s"
)

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    stream: Optional[object] = None,
) -> None:
    """Configure the root pxeos logger.

    Parameters
    ----------
    level:
        Log level name (DEBUG, INFO, WARNING, ERROR).
    json_format:
        If True, emit JSON-formatted log lines.
    stream:
        Output stream (defaults to sys.stderr).
    """
    level = level.upper()
    if level not in _VALID_LEVELS:
        level = "INFO"

    root_logger = logging.getLogger("pxeos")
    root_logger.setLevel(getattr(logging, level))

    # Remove existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setLevel(getattr(logging, level))

    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT))

    root_logger.addHandler(handler)
