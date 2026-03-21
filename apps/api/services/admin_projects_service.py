"""Admin projects service — listing and detail views with task counts."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from core.schemas.admin import ProjectDetailResult, ProjectListResult, ProjectWithStats
from db.models.task_item import TaskItem
from db.repositories.project_alias_repo import ProjectAliasRepo
from db.repositories.project_repo import ProjectRepository

logger = get_logger(__name__)


class AdminProjectsService:
    def __init__(
        self,
        project_repo: ProjectRepository,
        alias_repo: ProjectAliasRepo,
    ) -> None:
        self._project_repo = project_repo
        self._alias_repo = alias_repo

    async def list_projects(self, session: AsyncSession) -> ProjectListResult:
        """Return all active projects with per-project task counts."""
        projects = await self._project_repo.list_active()

        items: list[ProjectWithStats] = []
        for project in projects:
            count_result = await session.execute(
                select(func.count())
                .select_from(TaskItem)
                .where(
                    TaskItem.project_id == project.id,
                )
            )
            task_count = count_result.scalar_one()
            
            aliases = await self._alias_repo.list_by_project(project.id)
            alias_count = len(aliases)
            
            items.append(ProjectWithStats(project=project, task_count=task_count, alias_count=alias_count))

        return ProjectListResult(items=items, total=len(items))

    async def get_project_detail(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
    ) -> ProjectDetailResult | None:
        """Return project detail with task count and aliases, or None if not found."""
        project = await self._project_repo.get_by_id(project_id)
        if project is None:
            return None

        count_result = await session.execute(
            select(func.count())
            .select_from(TaskItem)
            .where(
                TaskItem.project_id == project_id,
            )
        )
        task_count = count_result.scalar_one()
        aliases = await self._alias_repo.list_by_project(project_id)

        return ProjectDetailResult(
            project=project,
            task_count=task_count,
            aliases=aliases,
        )
