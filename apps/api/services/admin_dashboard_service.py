"""Admin dashboard service — aggregates stats for the admin panel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from core.schemas.admin import DashboardStats
from db.models.task_item import TaskItem
from db.repositories.project_repo import ProjectRepository
from db.repositories.system_event_repo import SystemEventRepo

logger = get_logger(__name__)


class AdminDashboardService:
    def __init__(
        self,
        task_repo,  # TaskItemRepository
        project_repo: ProjectRepository,
        event_repo: SystemEventRepo,
    ) -> None:
        self._task_repo = task_repo
        self._project_repo = project_repo
        self._event_repo = event_repo

    async def get_dashboard_stats(self, session: AsyncSession) -> DashboardStats:
        """Collect all dashboard statistics in a single call."""
        # total tasks
        total_result = await session.execute(select(func.count()).select_from(TaskItem))
        total_tasks = total_result.scalar_one()

        # tasks by status
        status_result = await session.execute(
            select(TaskItem.status, func.count()).group_by(TaskItem.status)
        )
        tasks_by_status = {row[0]: row[1] for row in status_result.all()}

        # tasks today (created_at >= start of today UTC)
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_result = await session.execute(
            select(func.count()).select_from(TaskItem).where(TaskItem.created_at >= today_start)
        )
        tasks_today = today_result.scalar_one()

        # active projects
        active_projects_list = await self._project_repo.list_active()
        active_projects = len(active_projects_list)

        # recent events (last 10)
        recent_events = await self._event_repo.list_events(limit=10)

        # error count in last 24h
        since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        error_count_24h = await self._event_repo.count_events(severity="error", since=since_24h)

        # tasks by kind
        kind_result = await session.execute(
            select(TaskItem.kind, func.count()).group_by(TaskItem.kind)
        )
        tasks_by_kind = {row[0]: row[1] for row in kind_result.all()}

        return DashboardStats(
            total_tasks=total_tasks,
            tasks_by_status=tasks_by_status,
            tasks_today=tasks_today,
            active_projects=active_projects,
            recent_events=recent_events,
            error_count_24h=error_count_24h,
            tasks_by_kind=tasks_by_kind,
        )
