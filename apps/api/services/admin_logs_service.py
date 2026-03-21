"""Admin logs service for querying system events."""

import math
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from core.schemas.admin import EventListResult
from db.repositories.system_event_repo import SystemEventRepo

logger = get_logger(__name__)


class AdminLogsService:
    """Service for querying and managing system event logs."""

    def __init__(self, event_repo: SystemEventRepo) -> None:
        """Initialize with event repository.

        Args:
            event_repo: SystemEventRepo instance for database operations
        """
        self._event_repo = event_repo

    async def list_events(
        self,
        session: AsyncSession,
        event_type: str | None = None,
        severity: str | None = None,
        subsystem: str | None = None,
        since: datetime | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> EventListResult:
        """List system events with filtering and pagination.

        Args:
            session: SQLAlchemy async session
            event_type: Filter by event type (e.g., "task_created")
            severity: Filter by severity (e.g., "error", "warning", "info")
            subsystem: Filter by subsystem (e.g., "llm", "task_intake")
            since: Filter events created after this datetime
            page: Page number (1-indexed)
            per_page: Number of items per page

        Returns:
            EventListResult containing paginated events and metadata
        """
        offset = (page - 1) * per_page
        items = await self._event_repo.list_events(
            event_type, severity, subsystem, since, per_page, offset
        )
        total = await self._event_repo.count_events(event_type, severity, subsystem, since)
        total_pages = max(1, math.ceil(total / per_page))
        return EventListResult(
            items=items, total=total, page=page, per_page=per_page, total_pages=total_pages
        )

    async def get_severity_summary(
        self, session: AsyncSession, since: datetime | None = None
    ) -> dict[str, int]:
        """Get summary of event counts by severity level.

        Args:
            session: SQLAlchemy async session
            since: Only count events created after this datetime

        Returns:
            Dictionary mapping severity level to event count
        """
        return await self._event_repo.count_by_severity(since=since)
