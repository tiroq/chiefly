from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
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


@dataclass
class TaskListSyncResult:
    """Per-tasklist sync result."""

    tasklist_id: str
    tasklist_title: str
    tasks_seen: int = 0
    new_count: int = 0
    updated_count: int = 0
    moved_count: int = 0


@dataclass
class SyncCycleSummary:
    """Full sync cycle summary across all task lists."""

    tasklists_scanned: int = 0
    tasks_scanned: int = 0
    new_count: int = 0
    updated_count: int = 0
    moved_count: int = 0
    deleted_count: int = 0
    queued_count: int = 0
    tasklist_results: list[TaskListSyncResult] = field(default_factory=list)

    def add_tasklist_result(self, result: TaskListSyncResult) -> None:
        self.tasklist_results.append(result)
        self.tasklists_scanned += 1
        self.tasks_scanned += result.tasks_seen
        self.new_count += result.new_count
        self.updated_count += result.updated_count
        self.moved_count += result.moved_count

    @property
    def total_synced(self) -> int:
        return self.new_count + self.updated_count + self.moved_count


class SyncService:
    def __init__(
        self,
        session: AsyncSession,
        google_tasks: GoogleTasksService,
    ) -> None:
        self._session = session
        self._google_tasks = google_tasks

    async def sync_all(self) -> SyncCycleSummary:
        """Sync all Google Tasks task lists and their tasks.

        Iterates through all available task lists, syncs tasks for each,
        and performs missing/deleted task detection across the entire account.

        Returns:
            SyncCycleSummary: A summary of the sync operation including counts of
                new, updated, moved, and deleted tasks.
        """
        tasklists = self._google_tasks.list_tasklists()
        logger.info("sync_cycle_start", tasklists=len(tasklists))

        source_repo = SourceTaskRepository(self._session)
        queue_repo = ProcessingQueueRepository(self._session)
        record_repo = TaskRecordRepository(self._session)
        snapshot_repo = TaskSnapshotRepository(self._session)

        summary = SyncCycleSummary()
        all_seen_stable_ids: set[uuid.UUID] = set()

        for tl in tasklists:
            tasklist_id = tl["id"]
            tasklist_title = tl.get("title", "")

            result = await self._sync_tasklist(
                tasklist_id=tasklist_id,
                tasklist_title=tasklist_title,
                source_repo=source_repo,
                queue_repo=queue_repo,
                record_repo=record_repo,
                snapshot_repo=snapshot_repo,
                all_seen_stable_ids=all_seen_stable_ids,
            )
            summary.add_tasklist_result(result)

        # --- Missing / deleted detection across all lists ---
        deleted_count = await self._detect_missing(record_repo, all_seen_stable_ids)
        summary.deleted_count = deleted_count
        summary.queued_count = summary.new_count + summary.updated_count + summary.moved_count

        await self._session.commit()
        logger.info(
            "sync_cycle_complete",
            tasklists_scanned=summary.tasklists_scanned,
            tasks_scanned=summary.tasks_scanned,
            new_count=summary.new_count,
            updated_count=summary.updated_count,
            moved_count=summary.moved_count,
            deleted_count=summary.deleted_count,
            queued_count=summary.queued_count,
        )
        return summary

    async def sync_tasklist(self, tasklist_id: str) -> int:
        """Sync a single tasklist and return the count of synced tasks.

        Args:
            tasklist_id: The Google Tasks ID of the list to sync.

        Returns:
            int: Total number of new, updated, and moved tasks.
        """
        source_repo = SourceTaskRepository(self._session)
        queue_repo = ProcessingQueueRepository(self._session)
        record_repo = TaskRecordRepository(self._session)
        snapshot_repo = TaskSnapshotRepository(self._session)

        all_seen_stable_ids: set[uuid.UUID] = set()

        result = await self._sync_tasklist(
            tasklist_id=tasklist_id,
            tasklist_title="",
            source_repo=source_repo,
            queue_repo=queue_repo,
            record_repo=record_repo,
            snapshot_repo=snapshot_repo,
            all_seen_stable_ids=all_seen_stable_ids,
        )

        await self._detect_missing(record_repo, all_seen_stable_ids)
        await self._session.commit()
        return result.new_count + result.updated_count + result.moved_count

    async def sync_inbox(self, inbox_list_id: str) -> int:
        """Backward-compatible alias for sync_tasklist().

        Args:
            inbox_list_id: The Google Tasks ID of the default tasklist.

        Returns:
            int: Total number of synced tasks.
        """
        return await self.sync_tasklist(inbox_list_id)

    async def _sync_tasklist(
        self,
        tasklist_id: str,
        tasklist_title: str,
        source_repo: SourceTaskRepository,
        queue_repo: ProcessingQueueRepository,
        record_repo: TaskRecordRepository,
        snapshot_repo: TaskSnapshotRepository,
        all_seen_stable_ids: set[uuid.UUID],
    ) -> TaskListSyncResult:
        """Sync a single tasklist. Shared logic for sync_all() and sync_tasklist().

        Processes each task in the list, handles new tasks, updates, and moves
        between lists. Updates both source_tasks and task_records/snapshots.

        Args:
            tasklist_id: Google Tasks ID of the list.
            tasklist_title: Human-readable title of the list.
            source_repo: Repository for source task data.
            queue_repo: Repository for processing queue.
            record_repo: Repository for task records.
            snapshot_repo: Repository for task snapshots.
            all_seen_stable_ids: Set to track stable IDs seen during the sync cycle.

        Returns:
            TaskListSyncResult: Detailed results for this specific task list.
        """
        gtasks = self._google_tasks.list_tasks(tasklist_id)
        logger.info(
            "sync_tasklist_start",
            tasklist_id=tasklist_id,
            tasklist_title=tasklist_title,
            count=len(gtasks),
        )

        result = TaskListSyncResult(
            tasklist_id=tasklist_id,
            tasklist_title=tasklist_title,
        )

        for gtask in gtasks:
            if not gtask.title:
                continue

            result.tasks_seen += 1
            content_hash = compute_content_hash(gtask.title, gtask.notes)
            google_updated_at = self._parse_google_timestamp(gtask.updated)
            raw_payload = gtask.raw_payload or self._build_payload(gtask)
            envelope = notes_codec.parse(gtask.notes)

            # --- Dual-write: source_tasks (backward compat) ---
            source_task = await self._sync_source_task(
                source_repo, gtask, tasklist_id, content_hash, google_updated_at
            )

            # --- task_records + task_snapshots ---
            existing_record = await record_repo.get_by_pointer(tasklist_id, gtask.id)

            if existing_record is None:
                # Check if this task moved from a different list
                moved_record = await self._find_moved_record(
                    record_repo, snapshot_repo, gtask, tasklist_id
                )

                if moved_record is not None:
                    # Task moved from another tasklist
                    record_stable_id = moved_record.stable_id
                    all_seen_stable_ids.add(record_stable_id)

                    await record_repo.update_pointer(
                        record_stable_id, tasklist_id, gtask.id, gtask.updated
                    )
                    await record_repo.mark_seen(record_stable_id)
                    await record_repo.reset_misses(record_stable_id)

                    await snapshot_repo.create(
                        tasklist_id=tasklist_id,
                        task_id=gtask.id,
                        payload=raw_payload,
                        content_hash=content_hash,
                        stable_id=record_stable_id,
                        google_updated=gtask.updated,
                    )
                    _ = await queue_repo.enqueue_by_stable_id(
                        stable_id=record_stable_id,
                        source_task_id=source_task.id,
                        reason=ProcessingReason.TASK_MOVED,
                    )
                    result.moved_count += 1
                    logger.info(
                        "sync_task_moved",
                        google_task_id=gtask.id,
                        stable_id=str(record_stable_id),
                        from_tasklist=moved_record.current_tasklist_id,
                        to_tasklist=tasklist_id,
                    )
                else:
                    # Genuinely new task
                    stable_id, state = self._resolve_identity(envelope)
                    record = await record_repo.create(
                        stable_id=stable_id,
                        state=state,
                        processing_status=WorkflowStatus.PENDING,
                        current_tasklist_id=tasklist_id,
                        current_task_id=gtask.id,
                    )
                    record_stable_id = record.stable_id

                    await snapshot_repo.create(
                        tasklist_id=tasklist_id,
                        task_id=gtask.id,
                        payload=raw_payload,
                        content_hash=content_hash,
                        stable_id=record_stable_id,
                        google_updated=gtask.updated,
                    )

                    reason = ProcessingReason.NEW_TASK
                    _ = await queue_repo.enqueue_by_stable_id(
                        stable_id=record_stable_id,
                        source_task_id=source_task.id,
                        reason=reason,
                    )
                    result.new_count += 1
                    all_seen_stable_ids.add(record_stable_id)
                    logger.info(
                        "sync_new_task",
                        google_task_id=gtask.id,
                        stable_id=str(record_stable_id),
                        state=state.value,
                        tasklist_id=tasklist_id,
                    )

            else:
                record_stable_id = existing_record.stable_id
                all_seen_stable_ids.add(record_stable_id)

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
                    await snapshot_repo.create(
                        tasklist_id=tasklist_id,
                        task_id=gtask.id,
                        payload=raw_payload,
                        content_hash=content_hash,
                        stable_id=record_stable_id,
                        google_updated=gtask.updated,
                    )
                    _ = await queue_repo.enqueue_by_stable_id(
                        stable_id=record_stable_id,
                        source_task_id=source_task.id,
                        reason=ProcessingReason.SOURCE_CHANGED,
                    )
                    result.updated_count += 1
                    logger.info(
                        "sync_changed_task",
                        google_task_id=gtask.id,
                        stable_id=str(record_stable_id),
                        old_hash=old_hash,
                        new_hash=content_hash,
                        tasklist_id=tasklist_id,
                    )
                else:
                    await record_repo.update_pointer(
                        record_stable_id, tasklist_id, gtask.id, gtask.updated
                    )

        logger.info(
            "sync_tasklist_complete",
            tasklist_id=tasklist_id,
            tasklist_title=tasklist_title,
            tasks_seen=result.tasks_seen,
            new_count=result.new_count,
            updated_count=result.updated_count,
            moved_count=result.moved_count,
        )
        return result

    async def _find_moved_record(
        self,
        record_repo: TaskRecordRepository,
        snapshot_repo: TaskSnapshotRepository,
        gtask: GoogleTask,
        current_tasklist_id: str,
    ) -> object | None:
        """
        Check if a task that appears new in current_tasklist_id actually moved
        from a different list. We match by content hash against existing records
        whose pointer points to a different tasklist.
        """
        content_hash = compute_content_hash(gtask.title, gtask.notes)

        # Look for a record with the same google_task_id on a different list.
        # Google Tasks keeps task IDs unique within a user account when tasks
        # are moved via the UI (drag between lists). If the ID doesn't match,
        # this is a genuinely new task.
        #
        # We cannot just search by content hash because different tasks could
        # have the same title/notes. Instead we rely on a pragmatic heuristic:
        # if a task with the same google_task_id was tracked on a different list
        # and is now missing there, it's a move.
        tracked = await record_repo.list_active_and_missing()
        for record in tracked:
            if (
                record.current_task_id == gtask.id
                and record.current_tasklist_id != current_tasklist_id
            ):
                return record
        return None

    async def _sync_source_task(
        self,
        source_repo: SourceTaskRepository,
        gtask: GoogleTask,
        tasklist_id: str,
        content_hash: str,
        google_updated_at: datetime | None,
    ) -> SourceTask:
        existing = await source_repo.get_by_google_task_id(gtask.id)
        if existing is None:
            source_task = SourceTask(
                id=uuid.uuid4(),
                google_task_id=gtask.id,
                google_tasklist_id=tasklist_id,
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
            existing.google_tasklist_id = tasklist_id
            existing.synced_at = datetime.now(tz=timezone.utc)
            _ = await source_repo.upsert(existing)
            return existing

    def _resolve_identity(
        self,
        envelope: dict[str, object] | None,
    ) -> tuple[uuid.UUID, TaskRecordState]:
        if envelope and "stable_id" in envelope:
            try:
                stable_id = uuid.UUID(str(envelope["stable_id"]))
                return stable_id, TaskRecordState.ACTIVE
            except (ValueError, TypeError):
                pass
        return uuid.uuid4(), TaskRecordState.UNADOPTED

    async def _detect_missing(
        self,
        record_repo: TaskRecordRepository,
        seen_stable_ids: set[uuid.UUID],
    ) -> int:
        """Detect missing/deleted tasks. Returns count of newly deleted records."""
        deleted_count = 0
        tracked = await record_repo.list_active_and_missing()
        for record in tracked:
            if record.stable_id in seen_stable_ids:
                continue

            miss_count = await record_repo.increment_misses(record.stable_id)

            if miss_count >= MISSING_THRESHOLD:
                await record_repo.update_state(record.stable_id, TaskRecordState.DELETED)
                deleted_count += 1
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
        return deleted_count

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
