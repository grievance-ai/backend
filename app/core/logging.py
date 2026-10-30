"""Structured logging setup.

Configures structlog to emit JSON log lines. Call ``configure_logging()`` once
at application startup; use ``get_logger(__name__)`` everywhere else.
"""

import logging
import sys
from typing import cast

import structlog
from structlog.stdlib import BoundLogger
from structlog.types import Processor

from app.core.config import settings


def configure_logging() -> None:
    level = logging.getLevelName(settings.log_level.upper())
    if not isinstance(level, int):
        level = logging.INFO

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> BoundLogger:
    return cast(BoundLogger, structlog.get_logger(name))
