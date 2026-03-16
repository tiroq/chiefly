import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.task_revision import TaskRevision


class TaskRevisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_next_revision_no(self, task_item_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.max(TaskRevision.revision_no), 0)).where(
                TaskRevision.task_item_id == task_item_id
            )
        )
        return (result.scalar() or 0) + 1

    async def list_by_task(self, task_item_id: uuid.UUID) -> list[TaskRevision]:
        result = await self._session.execute(
            select(TaskRevision)
            .where(TaskRevision.task_item_id == task_item_id)
            .order_by(TaskRevision.revision_no)
        )
        return list(result.scalars().all())

    async def create(self, revision: TaskRevision) -> TaskRevision:
        self._session.add(revision)
        await self._session.flush()
        return revision
