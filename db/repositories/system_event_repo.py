from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.system_event import SystemEvent


class SystemEventRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, event: SystemEvent) -> SystemEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    def _apply_filters(
        self,
        stmt,
        event_type: str | None = None,
        severity: str | None = None,
        subsystem: str | None = None,
        since: datetime | None = None,
    ):
        if event_type is not None:
            stmt = stmt.where(SystemEvent.event_type == event_type)
        if severity is not None:
            stmt = stmt.where(SystemEvent.severity == severity)
        if subsystem is not None:
            stmt = stmt.where(SystemEvent.subsystem == subsystem)
        if since is not None:
            stmt = stmt.where(SystemEvent.created_at >= since)
        return stmt

    async def list_events(
        self,
        event_type: str | None = None,
        severity: str | None = None,
        subsystem: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SystemEvent]:
        stmt = select(SystemEvent).order_by(SystemEvent.created_at.desc())
        stmt = self._apply_filters(stmt, event_type, severity, subsystem, since)
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_events(
        self,
        event_type: str | None = None,
        severity: str | None = None,
        subsystem: str | None = None,
        since: datetime | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(SystemEvent)
        stmt = self._apply_filters(stmt, event_type, severity, subsystem, since)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def count_by_severity(self, since: datetime | None = None) -> dict[str, int]:
        stmt = select(SystemEvent.severity, func.count()).group_by(SystemEvent.severity)
        if since is not None:
            stmt = stmt.where(SystemEvent.created_at >= since)
        result = await self._session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}
