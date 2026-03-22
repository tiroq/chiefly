from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from core.schemas.admin import DashboardStats
from db.models.task_record import TaskRecord
from db.models.task_snapshot import TaskSnapshot
from db.repositories.project_repo import ProjectRepository
from db.repositories.system_event_repo import SystemEventRepo

logger = get_logger(__name__)


class AdminDashboardService:
    def __init__(
        self,
        project_repo: ProjectRepository,
        event_repo: SystemEventRepo,
    ) -> None:
        self._project_repo = project_repo
        self._event_repo = event_repo

    async def get_dashboard_stats(self, session: AsyncSession) -> DashboardStats:
        total_result = await session.execute(select(func.count()).select_from(TaskRecord))
        total_tasks = total_result.scalar_one()

        status_result = await session.execute(
            select(TaskRecord.processing_status, func.count()).group_by(
                TaskRecord.processing_status
            )
        )
        tasks_by_status = {row[0]: row[1] for row in status_result.all()}

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_result = await session.execute(
            select(func.count()).select_from(TaskRecord).where(TaskRecord.created_at >= today_start)
        )
        tasks_today = today_result.scalar_one()

        active_projects_list = await self._project_repo.list_active()
        active_projects = len(active_projects_list)

        recent_events = await self._event_repo.list_events(limit=10)

        since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        error_count_24h = await self._event_repo.count_events(severity="error", since=since_24h)

        kind_result = await session.execute(
            select(
                TaskSnapshot.payload["kind"].as_string(),
                func.count(),
            )
            .where(TaskSnapshot.is_latest == True)  # noqa: E712
            .group_by(TaskSnapshot.payload["kind"].as_string())
        )
        tasks_by_kind = {row[0]: row[1] for row in kind_result.all() if row[0] is not None}

        return DashboardStats(
            total_tasks=total_tasks,
            tasks_by_status=tasks_by_status,
            tasks_today=tasks_today,
            active_projects=active_projects,
            recent_events=recent_events,
            error_count_24h=error_count_24h,
            tasks_by_kind=tasks_by_kind,
        )
