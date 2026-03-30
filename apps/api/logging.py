import logging
import sys

import structlog

from apps.api.config import get_settings


class CompactSQLLogFilter(logging.Filter):
    """Keep SQLAlchemy query logs readable in one line."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith("sqlalchemy.engine") and isinstance(record.msg, str):
            record.msg = " ".join(record.msg.split())
        return True


def configure_logging() -> None:
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer()
            if settings.app_env == "development"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Route SQL logs through the app logger instead of SQLAlchemy's echo handler.
    # Only show SQL at DEBUG; INFO floods logs with every query on each poll cycle.
    engine_level = logging.DEBUG if log_level <= logging.DEBUG else logging.WARNING
    logging.getLogger("sqlalchemy.engine").setLevel(engine_level)
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(engine_level)

    # Suppress APScheduler's per-tick "Running job / executed successfully" chatter.
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.addFilter(CompactSQLLogFilter())


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
