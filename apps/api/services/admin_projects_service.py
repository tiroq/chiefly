from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from core.schemas.admin import ProjectDetailResult, ProjectListResult, ProjectWithStats
from db.models.system_event import SystemEvent
from db.models.task_record import TaskRecord
from db.models.task_snapshot import TaskSnapshot
from db.repositories.project_alias_repo import ProjectAliasRepo
from db.repositories.project_repo import ProjectRepository
from db.repositories.system_event_repo import SystemEventRepo

logger = get_logger(__name__)

_PROJECT_EVENT_TYPES = frozenset(
    {
        "project_discovered",
        "project_renamed",
        "project_deleted",
        "project_reactivated",
    }
)


class AdminProjectsService:
    def __init__(
        self,
        project_repo: ProjectRepository,
        alias_repo: ProjectAliasRepo,
        event_repo: SystemEventRepo | None = None,
    ) -> None:
        self._project_repo = project_repo
        self._alias_repo = alias_repo
        self._event_repo = event_repo

    async def _count_tasks_for_project(self, session: AsyncSession, project_id: uuid.UUID) -> int:
        count_result = await session.execute(
            select(func.count())
            .select_from(TaskRecord)
            .join(
                TaskSnapshot,
                (TaskSnapshot.stable_id == TaskRecord.stable_id) & (TaskSnapshot.is_latest == True),  # noqa: E712
            )
            .where(
                TaskSnapshot.payload["project_id"].as_string() == str(project_id),
            )
        )
        return count_result.scalar_one()

    async def list_projects(
        self,
        session: AsyncSession,
        include_deleted: bool = True,
    ) -> ProjectListResult:
        if include_deleted:
            projects = await self._project_repo.list_all_including_deleted()
        else:
            projects = await self._project_repo.list_active()

        items: list[ProjectWithStats] = []
        for project in projects:
            task_count = await self._count_tasks_for_project(session, project.id)

            aliases = await self._alias_repo.list_by_project(project.id)
            alias_count = len(aliases)

            items.append(
                ProjectWithStats(project=project, task_count=task_count, alias_count=alias_count)
            )

        return ProjectListResult(items=items, total=len(items))

    async def get_project_detail(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
    ) -> ProjectDetailResult | None:
        project = await self._project_repo.get_by_id(project_id)
        if project is None:
            return None

        task_count = await self._count_tasks_for_project(session, project_id)
        aliases = await self._alias_repo.list_by_project(project_id)

        recent_events: list[SystemEvent] = []
        if self._event_repo is not None:
            all_project_events = await self._event_repo.list_events(
                subsystem="project_sync",
                limit=20,
            )
            recent_events = [
                e
                for e in all_project_events
                if e.project_id == project_id and e.event_type in _PROJECT_EVENT_TYPES
            ]

        return ProjectDetailResult(
            project=project,
            task_count=task_count,
            aliases=aliases,
            recent_events=recent_events,
        )
