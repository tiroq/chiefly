import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.source_task import SourceTask


class SourceTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, source_task: SourceTask) -> tuple[SourceTask, bool]:
        """
        Insert or update a source task by google_task_id.
        Returns (source_task, is_new) — is_new is True if this was an insert.
        """
        existing = await self.get_by_google_task_id(source_task.google_task_id)
        if existing is not None:
            existing.title_raw = source_task.title_raw
            existing.notes_raw = source_task.notes_raw
            existing.google_status = source_task.google_status
            existing.google_updated_at = source_task.google_updated_at
            existing.google_tasklist_id = source_task.google_tasklist_id
            existing.content_hash = source_task.content_hash
            existing.is_deleted = source_task.is_deleted
            existing.synced_at = datetime.now(tz=timezone.utc)
            self._session.add(existing)
            await self._session.flush()
            return existing, False
        else:
            self._session.add(source_task)
            await self._session.flush()
            return source_task, True

    async def get_by_id(self, source_task_id: uuid.UUID) -> SourceTask | None:
        result = await self._session.execute(
            select(SourceTask).where(SourceTask.id == source_task_id)
        )
        return result.scalar_one_or_none()

    async def get_by_google_task_id(self, google_task_id: str) -> SourceTask | None:
        result = await self._session.execute(
            select(SourceTask).where(SourceTask.google_task_id == google_task_id)
        )
        return result.scalar_one_or_none()

    async def mark_deleted(self, google_task_id: str) -> None:
        """Mark a source task as deleted (soft delete)."""
        await self._session.execute(
            update(SourceTask)
            .where(SourceTask.google_task_id == google_task_id)
            .values(is_deleted=True, synced_at=datetime.now(tz=timezone.utc))
        )
        await self._session.flush()

    async def list_active(self) -> list[SourceTask]:
        result = await self._session.execute(
            select(SourceTask)
            .where(SourceTask.is_deleted == False)  # noqa: E712
            .order_by(SourceTask.synced_at.desc())
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[SourceTask]:
        result = await self._session.execute(
            select(SourceTask).order_by(SourceTask.synced_at.desc())
        )
        return list(result.scalars().all())
