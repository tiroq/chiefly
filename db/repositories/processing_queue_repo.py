import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.enums import ProcessingReason, ProcessingStatus
from db.models.task_processing_queue import TaskProcessingQueue

STALE_LOCK_TIMEOUT_SECONDS = 600


class ProcessingQueueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        source_task_id: uuid.UUID,
        reason: ProcessingReason,
    ) -> TaskProcessingQueue:
        entry = TaskProcessingQueue(
            id=uuid.uuid4(),
            source_task_id=source_task_id,
            processing_status=ProcessingStatus.PENDING,
            processing_reason=reason,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def enqueue_by_stable_id(
        self,
        stable_id: uuid.UUID,
        source_task_id: uuid.UUID,
        reason: ProcessingReason,
        snapshot_id: int | None = None,
    ) -> TaskProcessingQueue:
        entry = TaskProcessingQueue(
            id=uuid.uuid4(),
            source_task_id=source_task_id,
            stable_id=stable_id,
            processing_status=ProcessingStatus.PENDING,
            processing_reason=reason,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def claim_next(self, locked_by: str = "processing_worker") -> TaskProcessingQueue | None:
        """
        Atomically claim the next pending queue entry using SELECT FOR UPDATE SKIP LOCKED.
        Implements latest-only: skips older entries if newer exists for same source_task_id.
        Respects not_before: skips entries whose retry delay has not yet elapsed.
        Reclaims stale LOCKED/PROCESSING entries older than STALE_LOCK_TIMEOUT_SECONDS.
        """
        now = datetime.now(tz=timezone.utc)
        stale_cutoff = now - timedelta(seconds=STALE_LOCK_TIMEOUT_SECONDS)
        stmt = (
            select(TaskProcessingQueue)
            .where(
                or_(
                    (TaskProcessingQueue.processing_status == ProcessingStatus.PENDING)
                    & or_(
                        TaskProcessingQueue.not_before.is_(None),
                        TaskProcessingQueue.not_before <= now,
                    ),
                    (TaskProcessingQueue.processing_status == ProcessingStatus.LOCKED)
                    & (TaskProcessingQueue.locked_at < stale_cutoff),
                    (TaskProcessingQueue.processing_status == ProcessingStatus.PROCESSING)
                    & (TaskProcessingQueue.locked_at < stale_cutoff),
                ),
            )
            .order_by(TaskProcessingQueue.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        entry = result.scalar_one_or_none()

        if entry is None:
            return None

        # Latest-only: check if there's a newer pending entry for the same source_task
        newer_check = await self._session.execute(
            select(func.count(TaskProcessingQueue.id)).where(
                TaskProcessingQueue.source_task_id == entry.source_task_id,
                TaskProcessingQueue.processing_status == ProcessingStatus.PENDING,
                TaskProcessingQueue.created_at > entry.created_at,
            )
        )
        has_newer = (newer_check.scalar() or 0) > 0

        if has_newer:
            entry.processing_status = ProcessingStatus.SKIPPED
            entry.completed_at = datetime.now(tz=timezone.utc)
            self._session.add(entry)
            await self._session.flush()
            return await self.claim_next(locked_by=locked_by)

        now = datetime.now(tz=timezone.utc)
        entry.processing_status = ProcessingStatus.LOCKED
        entry.locked_at = now
        entry.locked_by = locked_by
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def mark_processing(self, entry_id: uuid.UUID, content_hash: str) -> None:
        await self._session.execute(
            update(TaskProcessingQueue)
            .where(TaskProcessingQueue.id == entry_id)
            .values(
                processing_status=ProcessingStatus.PROCESSING,
                content_hash_at_processing=content_hash,
                updated_at=datetime.now(tz=timezone.utc),
            )
        )
        await self._session.flush()

    async def complete(self, entry_id: uuid.UUID) -> None:
        now = datetime.now(tz=timezone.utc)
        await self._session.execute(
            update(TaskProcessingQueue)
            .where(TaskProcessingQueue.id == entry_id)
            .values(
                processing_status=ProcessingStatus.COMPLETED,
                completed_at=now,
                updated_at=now,
            )
        )
        await self._session.flush()

    async def fail(
        self, entry_id: uuid.UUID, error_message: str, not_before: datetime | None = None
    ) -> ProcessingStatus:
        result = await self._session.execute(
            select(TaskProcessingQueue).where(TaskProcessingQueue.id == entry_id)
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            return ProcessingStatus.FAILED

        now = datetime.now(tz=timezone.utc)
        new_retry_count = entry.retry_count + 1

        if new_retry_count >= entry.max_retries:
            new_status = ProcessingStatus.FAILED
        else:
            new_status = ProcessingStatus.PENDING

        effective_not_before = not_before if new_status == ProcessingStatus.PENDING else None

        await self._session.execute(
            update(TaskProcessingQueue)
            .where(TaskProcessingQueue.id == entry_id)
            .values(
                processing_status=new_status,
                retry_count=new_retry_count,
                error_message=error_message,
                locked_at=None,
                locked_by=None,
                not_before=effective_not_before,
                updated_at=now,
            )
        )
        await self._session.flush()
        return new_status

    async def requeue_with_delay(
        self, entry_id: uuid.UUID, error_message: str, not_before: datetime
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        await self._session.execute(
            update(TaskProcessingQueue)
            .where(TaskProcessingQueue.id == entry_id)
            .values(
                processing_status=ProcessingStatus.PENDING,
                error_message=error_message,
                locked_at=None,
                locked_by=None,
                not_before=not_before,
                updated_at=now,
            )
        )
        await self._session.flush()

    async def get_by_id(self, entry_id: uuid.UUID) -> TaskProcessingQueue | None:
        result = await self._session.execute(
            select(TaskProcessingQueue).where(TaskProcessingQueue.id == entry_id)
        )
        return result.scalar_one_or_none()

    async def count_pending(self) -> int:
        """Count queue entries waiting to be claimed (status=PENDING)."""
        result = await self._session.execute(
            select(func.count(TaskProcessingQueue.id)).where(
                TaskProcessingQueue.processing_status == ProcessingStatus.PENDING
            )
        )
        return result.scalar() or 0

    async def count_in_progress(self) -> int:
        """Count queue entries currently being worked on (LOCKED or PROCESSING)."""
        result = await self._session.execute(
            select(func.count(TaskProcessingQueue.id)).where(
                TaskProcessingQueue.processing_status.in_([
                    ProcessingStatus.LOCKED,
                    ProcessingStatus.PROCESSING,
                ])
            )
        )
        return result.scalar() or 0

    async def count_failed(self) -> int:
        """Count queue entries that have terminally failed (all retries exhausted)."""
        result = await self._session.execute(
            select(func.count(TaskProcessingQueue.id)).where(
                TaskProcessingQueue.processing_status == ProcessingStatus.FAILED
            )
        )
        return result.scalar() or 0

    async def list_pending(self, limit: int = 20) -> list[TaskProcessingQueue]:
        result = await self._session.execute(
            select(TaskProcessingQueue)
            .where(TaskProcessingQueue.processing_status == ProcessingStatus.PENDING)
            .order_by(TaskProcessingQueue.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_in_progress(self, limit: int = 20) -> list[TaskProcessingQueue]:
        """List entries currently being worked on (LOCKED or PROCESSING)."""
        result = await self._session.execute(
            select(TaskProcessingQueue)
            .where(
                TaskProcessingQueue.processing_status.in_([
                    ProcessingStatus.LOCKED,
                    ProcessingStatus.PROCESSING,
                ])
            )
            .order_by(TaskProcessingQueue.locked_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_failed(self, limit: int = 20) -> list[TaskProcessingQueue]:
        """List entries that have terminally failed (all retries exhausted)."""
        result = await self._session.execute(
            select(TaskProcessingQueue)
            .where(TaskProcessingQueue.processing_status == ProcessingStatus.FAILED)
            .order_by(TaskProcessingQueue.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_retry_pending(self, limit: int = 20) -> list[TaskProcessingQueue]:
        """List entries that failed at least once and are queued for retry (PENDING with retry_count > 0)."""
        now = datetime.now(tz=timezone.utc)
        result = await self._session.execute(
            select(TaskProcessingQueue)
            .where(
                TaskProcessingQueue.processing_status == ProcessingStatus.PENDING,
                TaskProcessingQueue.retry_count > 0,
                or_(
                    TaskProcessingQueue.not_before.is_(None),
                    TaskProcessingQueue.not_before <= now,
                ),
            )
            .order_by(TaskProcessingQueue.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_source_task(self, source_task_id: uuid.UUID) -> list[TaskProcessingQueue]:
        result = await self._session.execute(
            select(TaskProcessingQueue)
            .where(TaskProcessingQueue.source_task_id == source_task_id)
            .order_by(TaskProcessingQueue.created_at.desc())
        )
        return list(result.scalars().all())
