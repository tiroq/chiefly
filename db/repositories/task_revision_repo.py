import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.task_revision import TaskRevision


class TaskRevisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_next_revision_no_by_stable_id(self, stable_id: uuid.UUID) -> int:
        """Get next revision number for a task by stable_id."""
        result = await self._session.execute(
            select(func.coalesce(func.max(TaskRevision.revision_no), 0)).where(
                TaskRevision.stable_id == stable_id
            )
        )
        return (result.scalar() or 0) + 1

    async def get_by_correlation_id(self, correlation_id: uuid.UUID) -> TaskRevision | None:
        """Look up a revision by correlation_id for idempotency checks."""
        result = await self._session.execute(
            select(TaskRevision).where(TaskRevision.correlation_id == correlation_id)
        )
        return result.scalar_one_or_none()

    async def list_by_stable_id(self, stable_id: uuid.UUID) -> list[TaskRevision]:
        """List all revisions for a task by stable_id."""
        result = await self._session.execute(
            select(TaskRevision)
            .where(TaskRevision.stable_id == stable_id)
            .order_by(TaskRevision.revision_no)
        )
        return list(result.scalars().all())

    async def create(self, revision: TaskRevision) -> TaskRevision:
        self._session.add(revision)
        await self._session.flush()
        return revision
