"""Structured logging for the Agentic Software Factory.

Uses `structlog` for JSON-structured logs with trace/span context, agent role,
and phase binding. Falls back to standard library logging if structlog is
unavailable.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

try:
    import structlog

    _HAS_STRUCTLOG = True
except ImportError:  # pragma: no cover
    _HAS_STRUCTLOG = False


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    """Configure structured logging for the application."""
    if _HAS_STRUCTLOG:
        processors: list[Any] = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
        ]
        if json_logs:
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.dev.ConsoleRenderer(colors=False))

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level, logging.INFO)),
            logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
            cache_logger_on_first_use=True,
        )
    else:
        logging.basicConfig(
            level=getattr(logging, level, logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            stream=sys.stdout,
        )


def get_logger(name: str) -> Any:
    """Return a logger bound to `name`."""
    if _HAS_STRUCTLOG:
        return structlog.get_logger(name)
    return logging.getLogger(name)


__all__ = ["configure_logging", "get_logger"]
