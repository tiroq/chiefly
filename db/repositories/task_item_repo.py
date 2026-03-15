import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.enums import TaskStatus
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
