from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.google_tasks_service import GoogleTask, GoogleTasksService
from core.domain.enums import ProcessingReason, TaskRecordState, WorkflowStatus
from core.domain import notes_codec
from db.models.source_task import SourceTask
from db.repositories.processing_queue_repo import ProcessingQueueRepository
from db.repositories.source_task_repo import SourceTaskRepository
from db.repositories.task_record_repo import TaskRecordRepository
from db.repositories.task_snapshot_repo import TaskSnapshotRepository

logger = get_logger(__name__)

MISSING_THRESHOLD = 3


def compute_content_hash(title: str, notes: str | None) -> str:
    normalized = title.strip().lower()
    if notes:
        normalized += "\n" + notes.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class SyncService:
    def __init__(
        self,
        session: AsyncSession,
        google_tasks: GoogleTasksService,
    ) -> None:
        self._session = session
        self._google_tasks = google_tasks

    async def sync_inbox(self, inbox_list_id: str) -> int:
        gtasks = self._google_tasks.list_tasks(inbox_list_id)
        logger.info("sync_inbox_start", count=len(gtasks), tasklist_id=inbox_list_id)

        source_repo = SourceTaskRepository(self._session)
        queue_repo = ProcessingQueueRepository(self._session)
        record_repo = TaskRecordRepository(self._session)
        snapshot_repo = TaskSnapshotRepository(self._session)

        synced = 0
        seen_stable_ids: set[uuid.UUID] = set()

        for gtask in gtasks:
            if not gtask.title:
                continue

            content_hash = compute_content_hash(gtask.title, gtask.notes)
            google_updated_at = self._parse_google_timestamp(gtask.updated)
            raw_payload = gtask.raw_payload or self._build_payload(gtask)
            envelope = notes_codec.parse(gtask.notes)

            # --- Dual-write: source_tasks (backward compat) ---
            source_task = await self._sync_source_task(
                source_repo, gtask, inbox_list_id, content_hash, google_updated_at
            )

            # --- New path: task_records + task_snapshots ---
            existing_record = await record_repo.get_by_pointer(inbox_list_id, gtask.id)

            if existing_record is None:
                stable_id, state = self._resolve_identity(envelope)
                record = await record_repo.create(
                    stable_id=stable_id,
                    state=state,
                    processing_status=WorkflowStatus.PENDING,
                    current_tasklist_id=inbox_list_id,
                    current_task_id=gtask.id,
                )
                record_stable_id = record.stable_id

                snapshot = await snapshot_repo.create(
                    tasklist_id=inbox_list_id,
                    task_id=gtask.id,
                    payload=raw_payload,
                    content_hash=content_hash,
                    stable_id=record_stable_id,
                    google_updated=gtask.updated,
                )

                reason = ProcessingReason.NEW_TASK
                await queue_repo.enqueue_by_stable_id(
                    stable_id=record_stable_id,
                    source_task_id=source_task.id,
                    reason=reason,
                )
                synced += 1
                seen_stable_ids.add(record_stable_id)
                logger.info(
                    "sync_new_task",
                    google_task_id=gtask.id,
                    stable_id=str(record_stable_id),
                    state=state.value,
                )

            else:
                record_stable_id = existing_record.stable_id
                seen_stable_ids.add(record_stable_id)

                await record_repo.mark_seen(record_stable_id)
                await record_repo.reset_misses(record_stable_id)

                if existing_record.state in (
                    TaskRecordState.MISSING.value,
                    TaskRecordState.DELETED.value,
                ):
                    await record_repo.update_state(record_stable_id, TaskRecordState.ACTIVE)
                    logger.info(
                        "sync_task_reappeared",
                        google_task_id=gtask.id,
                        stable_id=str(record_stable_id),
                        previous_state=existing_record.state,
                    )

                latest_snapshot = await snapshot_repo.get_latest_by_stable_id(record_stable_id)
                old_hash = latest_snapshot.content_hash if latest_snapshot else None

                if old_hash != content_hash:
                    snapshot = await snapshot_repo.create(
                        tasklist_id=inbox_list_id,
                        task_id=gtask.id,
                        payload=raw_payload,
                        content_hash=content_hash,
                        stable_id=record_stable_id,
                        google_updated=gtask.updated,
                    )
                    await queue_repo.enqueue_by_stable_id(
                        stable_id=record_stable_id,
                        source_task_id=source_task.id,
                        reason=ProcessingReason.SOURCE_CHANGED,
                    )
                    synced += 1
                    logger.info(
                        "sync_changed_task",
                        google_task_id=gtask.id,
                        stable_id=str(record_stable_id),
                        old_hash=old_hash,
                        new_hash=content_hash,
                    )
                else:
                    await record_repo.update_pointer(
                        record_stable_id, inbox_list_id, gtask.id, gtask.updated
                    )

        # --- Missing detection ---
        await self._detect_missing(record_repo, seen_stable_ids)

        await self._session.commit()
        logger.info("sync_inbox_complete", synced=synced, total_seen=len(seen_stable_ids))
        return synced

    async def _sync_source_task(
        self,
        source_repo: SourceTaskRepository,
        gtask: GoogleTask,
        inbox_list_id: str,
        content_hash: str,
        google_updated_at: datetime | None,
    ) -> SourceTask:
        existing = await source_repo.get_by_google_task_id(gtask.id)
        if existing is None:
            source_task = SourceTask(
                id=uuid.uuid4(),
                google_task_id=gtask.id,
                google_tasklist_id=inbox_list_id,
                title_raw=gtask.title,
                notes_raw=gtask.notes,
                google_status=gtask.status,
                google_updated_at=google_updated_at,
                content_hash=content_hash,
            )
            source_task, _ = await source_repo.upsert(source_task)
            return source_task
        else:
            existing.title_raw = gtask.title
            existing.notes_raw = gtask.notes
            existing.google_status = gtask.status
            existing.google_updated_at = google_updated_at
            existing.content_hash = content_hash
            existing.synced_at = datetime.now(tz=timezone.utc)
            await source_repo.upsert(existing)
            return existing

    def _resolve_identity(
        self,
        envelope: dict[str, object] | None,
    ) -> tuple[uuid.UUID, TaskRecordState]:
        if envelope and "stable_id" in envelope:
            try:
                stable_id = uuid.UUID(envelope["stable_id"])
                return stable_id, TaskRecordState.ACTIVE
            except (ValueError, TypeError):
                pass
        return uuid.uuid4(), TaskRecordState.UNADOPTED

    async def _detect_missing(
        self,
        record_repo: TaskRecordRepository,
        seen_stable_ids: set[uuid.UUID],
    ) -> None:
        tracked = await record_repo.list_active_and_missing()
        for record in tracked:
            if record.stable_id in seen_stable_ids:
                continue

            miss_count = await record_repo.increment_misses(record.stable_id)

            if miss_count >= MISSING_THRESHOLD:
                await record_repo.update_state(record.stable_id, TaskRecordState.DELETED)
                logger.info(
                    "sync_task_deleted",
                    stable_id=str(record.stable_id),
                    miss_count=miss_count,
                )
            elif record.state != TaskRecordState.MISSING.value:
                await record_repo.update_state(record.stable_id, TaskRecordState.MISSING)
                logger.info(
                    "sync_task_missing",
                    stable_id=str(record.stable_id),
                    miss_count=miss_count,
                )

    def _build_payload(self, gtask: GoogleTask) -> dict[str, object]:
        payload: dict[str, object] = {"id": gtask.id, "title": gtask.title, "status": gtask.status}
        if gtask.notes:
            payload["notes"] = gtask.notes
        if gtask.due:
            payload["due"] = gtask.due
        if gtask.updated:
            payload["updated"] = gtask.updated
        return payload

    def _parse_google_timestamp(self, ts: str | None) -> datetime | None:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
