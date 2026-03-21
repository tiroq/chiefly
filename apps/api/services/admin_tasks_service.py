from __future__ import annotations

import math
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from core.domain.enums import TaskKind, TaskStatus
from core.schemas.admin import TaskDetailResult, TaskListResult
from db.repositories.task_item_repo import TaskItemRepository
from db.repositories.task_revision_repo import TaskRevisionRepository

logger = get_logger(__name__)


class AdminTasksService:
    def __init__(
        self,
        task_repo: TaskItemRepository,
        revision_repo: TaskRevisionRepository,
    ) -> None:
        self._task_repo = task_repo
        self._revision_repo = revision_repo

    async def list_tasks(
        self,
        session: AsyncSession,
        status: TaskStatus | None = None,
        kind: TaskKind | None = None,
        project_id: uuid.UUID | None = None,
        search: str | None = None,
        page: int = 1,
        per_page: int = 25,
    ) -> TaskListResult:
        offset = (page - 1) * per_page
        items = await self._task_repo.list_tasks_filtered(
            status, kind, project_id, search, per_page, offset
        )
        total = await self._task_repo.count_tasks_filtered(
            status, kind, project_id, search
        )
        total_pages = max(1, math.ceil(total / per_page))
        return TaskListResult(
            items=items,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        )

    async def get_task_detail(
        self,
        session: AsyncSession,
        task_id: uuid.UUID,
    ) -> TaskDetailResult | None:
        task = await self._task_repo.get_by_id(task_id)
        if task is None:
            return None
        revisions = await self._revision_repo.list_by_task(task_id)
        return TaskDetailResult(task=task, revisions=revisions)
