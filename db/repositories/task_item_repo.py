import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.enums import TaskKind, TaskStatus
from db.models.task_item import TaskItem


class TaskItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, task_id: uuid.UUID) -> TaskItem | None:
        result = await self._session.execute(
            select(TaskItem).where(TaskItem.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_by_source_google_task_id(self, google_task_id: str) -> TaskItem | None:
        result = await self._session.execute(
            select(TaskItem).where(TaskItem.source_google_task_id == google_task_id)
        )
        return result.scalar_one_or_none()

    async def list_by_status(self, status: TaskStatus) -> list[TaskItem]:
        result = await self._session.execute(
            select(TaskItem).where(TaskItem.status == status).order_by(TaskItem.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_active_routed(self, limit: int = 10) -> list[TaskItem]:
        result = await self._session.execute(
            select(TaskItem)
            .where(TaskItem.status == TaskStatus.ROUTED)
            .order_by(TaskItem.confirmed_at.desc().nulls_last())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create(self, task: TaskItem) -> TaskItem:
        self._session.add(task)
        await self._session.flush()
        return task

    async def save(self, task: TaskItem) -> TaskItem:
        self._session.add(task)
        await self._session.flush()
        return task

    async def list_tasks_filtered(
        self,
        status: TaskStatus | None = None,
        kind: TaskKind | None = None,
        project_id: uuid.UUID | None = None,
        search: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[TaskItem]:
        stmt = select(TaskItem).order_by(TaskItem.created_at.desc())
        if status is not None:
            stmt = stmt.where(TaskItem.status == status)
        if kind is not None:
            stmt = stmt.where(TaskItem.kind == kind)
        if project_id is not None:
            stmt = stmt.where(TaskItem.project_id == project_id)
        if search is not None:
            term = f"%{search}%"
            stmt = stmt.where(
                or_(
                    TaskItem.raw_text.ilike(term),
                    TaskItem.normalized_title.ilike(term),
                )
            )
        result = await self._session.execute(stmt.limit(limit).offset(offset))
        return list(result.scalars().all())

    async def count_tasks_filtered(
        self,
        status: TaskStatus | None = None,
        kind: TaskKind | None = None,
        project_id: uuid.UUID | None = None,
        search: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(TaskItem)
        if status is not None:
            stmt = stmt.where(TaskItem.status == status)
        if kind is not None:
            stmt = stmt.where(TaskItem.kind == kind)
        if project_id is not None:
            stmt = stmt.where(TaskItem.project_id == project_id)
        if search is not None:
            term = f"%{search}%"
            stmt = stmt.where(
                or_(
                    TaskItem.raw_text.ilike(term),
                    TaskItem.normalized_title.ilike(term),
                )
            )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def list_all(self) -> list[TaskItem]:
        """List all tasks without filters."""
        result = await self._session.execute(
            select(TaskItem).order_by(TaskItem.created_at.desc())
        )
        return list(result.scalars().all())
