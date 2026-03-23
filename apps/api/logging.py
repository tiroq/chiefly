import logging
import re
import sys

import structlog

from apps.api.config import get_settings


class StructuredSQLFilter(logging.Filter):
    """Convert raw SQLAlchemy SQL logs to terse structured messages.

    INSERT/UPDATE/DELETE lines are kept as a single-line summary with the
    table name.  Everything else (parameters, [cached …], BEGIN, COMMIT,
    ROLLBACK, SELECT) is suppressed so the log stream stays readable.
    """

    _INSERT_RE = re.compile(r"INSERT\s+INTO\s+(\w+)", re.IGNORECASE)
    _UPDATE_RE = re.compile(r"UPDATE\s+(\w+)", re.IGNORECASE)
    _DELETE_RE = re.compile(r"DELETE\s+FROM\s+(\w+)", re.IGNORECASE)
    _SUPPRESS_RE = re.compile(
        r"^\s*(\[|BEGIN|COMMIT|ROLLBACK|SELECT|SHOW|SET\s)",
        re.IGNORECASE,
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.name.startswith("sqlalchemy.engine"):
            return True
        msg = record.msg if isinstance(record.msg, str) else ""
        msg = " ".join(msg.split())
        if m := self._INSERT_RE.search(msg):
            record.msg = f"sql_insert  table={m.group(1)}"
            return True
        if m := self._UPDATE_RE.search(msg):
            record.msg = f"sql_update  table={m.group(1)}"
            return True
        if m := self._DELETE_RE.search(msg):
            record.msg = f"sql_delete  table={m.group(1)}"
            return True
        # Suppress SELECT, BEGIN, COMMIT, ROLLBACK, parameter lines, etc.
        return False


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
    engine_level = logging.INFO if settings.app_env == "development" else logging.WARNING
    logging.getLogger("sqlalchemy.engine").setLevel(engine_level)
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(engine_level)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.addFilter(StructuredSQLFilter())


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
