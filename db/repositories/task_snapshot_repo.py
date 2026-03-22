import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.task_snapshot import TaskSnapshot


class TaskSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        tasklist_id: str,
        task_id: str,
        payload: dict[str, Any],
        content_hash: str,
        stable_id: uuid.UUID | None = None,
        google_updated: str | None = None,
        is_latest: bool = True,
    ) -> TaskSnapshot:
        if is_latest and stable_id is not None:
            await self._clear_latest(stable_id)

        snapshot = TaskSnapshot(
            stable_id=stable_id,
            tasklist_id=tasklist_id,
            task_id=task_id,
            google_updated=google_updated,
            payload=payload,
            content_hash=content_hash,
            is_latest=is_latest,
        )
        self._session.add(snapshot)
        await self._session.flush()
        return snapshot

    async def get_by_id(self, snapshot_id: int) -> TaskSnapshot | None:
        result = await self._session.execute(
            select(TaskSnapshot).where(TaskSnapshot.id == snapshot_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_by_stable_id(self, stable_id: uuid.UUID) -> TaskSnapshot | None:
        result = await self._session.execute(
            select(TaskSnapshot)
            .where(
                TaskSnapshot.stable_id == stable_id,
                TaskSnapshot.is_latest == True,  # noqa: E712
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_by_task(self, tasklist_id: str, task_id: str) -> TaskSnapshot | None:
        result = await self._session.execute(
            select(TaskSnapshot)
            .where(
                TaskSnapshot.tasklist_id == tasklist_id,
                TaskSnapshot.task_id == task_id,
                TaskSnapshot.is_latest == True,  # noqa: E712
            )
            .order_by(TaskSnapshot.fetched_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_stable_id(self, stable_id: uuid.UUID, limit: int = 50) -> list[TaskSnapshot]:
        result = await self._session.execute(
            select(TaskSnapshot)
            .where(TaskSnapshot.stable_id == stable_id)
            .order_by(TaskSnapshot.fetched_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_stable_id(self, snapshot_id: int, stable_id: uuid.UUID) -> None:
        await self._session.execute(
            update(TaskSnapshot).where(TaskSnapshot.id == snapshot_id).values(stable_id=stable_id)
        )
        await self._session.flush()

    async def _clear_latest(self, stable_id: uuid.UUID) -> None:
        await self._session.execute(
            update(TaskSnapshot)
            .where(
                TaskSnapshot.stable_id == stable_id,
                TaskSnapshot.is_latest == True,  # noqa: E712
            )
            .values(is_latest=False)
        )
        await self._session.flush()
