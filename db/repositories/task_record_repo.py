import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.enums import TaskRecordState, WorkflowStatus
from db.models.task_record import TaskRecord


class TaskRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        stable_id: uuid.UUID,
        state: TaskRecordState = TaskRecordState.UNADOPTED,
        processing_status: WorkflowStatus = WorkflowStatus.PENDING,
        current_tasklist_id: str | None = None,
        current_task_id: str | None = None,
    ) -> TaskRecord:
        record = TaskRecord(
            stable_id=stable_id,
            state=state.value,
            processing_status=processing_status.value,
            current_tasklist_id=current_tasklist_id,
            current_task_id=current_task_id,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_by_stable_id(self, stable_id: uuid.UUID) -> TaskRecord | None:
        result = await self._session.execute(
            select(TaskRecord).where(TaskRecord.stable_id == stable_id)
        )
        return result.scalar_one_or_none()

    async def get_by_pointer(self, tasklist_id: str, task_id: str) -> TaskRecord | None:
        result = await self._session.execute(
            select(TaskRecord).where(
                TaskRecord.current_tasklist_id == tasklist_id,
                TaskRecord.current_task_id == task_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_pointer(
        self,
        stable_id: uuid.UUID,
        tasklist_id: str,
        task_id: str,
        google_updated: str | None = None,
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        await self._session.execute(
            update(TaskRecord)
            .where(TaskRecord.stable_id == stable_id)
            .values(
                current_tasklist_id=tasklist_id,
                current_task_id=task_id,
                pointer_updated_at=now,
                last_seen_at=now,
                last_google_updated=google_updated,
                updated_at=now,
            )
        )
        await self._session.flush()

    async def update_state(
        self,
        stable_id: uuid.UUID,
        state: TaskRecordState,
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        await self._session.execute(
            update(TaskRecord)
            .where(TaskRecord.stable_id == stable_id)
            .values(state=state.value, updated_at=now)
        )
        await self._session.flush()

    async def update_processing_status(
        self,
        stable_id: uuid.UUID,
        status: WorkflowStatus,
        error: str | None = None,
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        values: dict[str, object] = {
            "processing_status": status.value,
            "processing_status_updated_at": now,
            "updated_at": now,
        }
        if error is not None:
            values["last_error"] = error
        await self._session.execute(
            update(TaskRecord).where(TaskRecord.stable_id == stable_id).values(**values)
        )
        await self._session.flush()

    async def mark_seen(self, stable_id: uuid.UUID) -> None:
        now = datetime.now(tz=timezone.utc)
        await self._session.execute(
            update(TaskRecord)
            .where(TaskRecord.stable_id == stable_id)
            .values(last_seen_at=now, updated_at=now)
        )
        await self._session.flush()

    async def list_by_state(self, state: TaskRecordState) -> list[TaskRecord]:
        result = await self._session.execute(
            select(TaskRecord)
            .where(TaskRecord.state == state.value)
            .order_by(TaskRecord.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_active(self) -> list[TaskRecord]:
        return await self.list_by_state(TaskRecordState.ACTIVE)

    async def list_active_and_missing(self) -> list[TaskRecord]:
        """List all task records with state active or missing (for sync missing detection)."""
        result = await self._session.execute(
            select(TaskRecord)
            .where(
                TaskRecord.state.in_([TaskRecordState.ACTIVE.value, TaskRecordState.MISSING.value])
            )
            .order_by(TaskRecord.created_at.desc())
        )
        return list(result.scalars().all())

    async def increment_misses(self, stable_id: uuid.UUID) -> int:
        """Increment consecutive_misses and return the new count."""
        record = await self.get_by_stable_id(stable_id)
        if record is None:
            return 0
        new_count = record.consecutive_misses + 1
        now = datetime.now(tz=timezone.utc)
        await self._session.execute(
            update(TaskRecord)
            .where(TaskRecord.stable_id == stable_id)
            .values(consecutive_misses=new_count, updated_at=now)
        )
        await self._session.flush()
        return new_count

    async def reset_misses(self, stable_id: uuid.UUID) -> None:
        """Reset consecutive_misses to 0."""
        now = datetime.now(tz=timezone.utc)
        await self._session.execute(
            update(TaskRecord)
            .where(TaskRecord.stable_id == stable_id)
            .values(consecutive_misses=0, updated_at=now)
        )
        await self._session.flush()
