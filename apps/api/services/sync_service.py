from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.google_tasks_service import GoogleTask, GoogleTasksService
from core.domain.enums import ProcessingReason
from db.models.source_task import SourceTask
from db.repositories.processing_queue_repo import ProcessingQueueRepository
from db.repositories.source_task_repo import SourceTaskRepository

logger = get_logger(__name__)


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

        synced = 0
        seen_google_ids: set[str] = set()

        for gtask in gtasks:
            if not gtask.title:
                continue

            seen_google_ids.add(gtask.id)

            content_hash = compute_content_hash(gtask.title, gtask.notes)
            google_updated_at = self._parse_google_timestamp(gtask.updated)

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
                await queue_repo.enqueue(
                    source_task_id=source_task.id,
                    reason=ProcessingReason.NEW_TASK,
                )
                synced += 1
                logger.info(
                    "sync_new_task",
                    google_task_id=gtask.id,
                    source_task_id=str(source_task.id),
                )
            elif existing.content_hash != content_hash:
                existing.title_raw = gtask.title
                existing.notes_raw = gtask.notes
                existing.google_status = gtask.status
                existing.google_updated_at = google_updated_at
                existing.content_hash = content_hash
                existing.synced_at = datetime.now(tz=timezone.utc)
                await source_repo.upsert(existing)
                await queue_repo.enqueue(
                    source_task_id=existing.id,
                    reason=ProcessingReason.SOURCE_CHANGED,
                )
                synced += 1
                logger.info(
                    "sync_changed_task",
                    google_task_id=gtask.id,
                    old_hash=existing.content_hash,
                    new_hash=content_hash,
                )
            else:
                existing.synced_at = datetime.now(tz=timezone.utc)
                existing.google_status = gtask.status
                self._session.add(existing)
                await self._session.flush()

        await self._session.commit()
        logger.info("sync_inbox_complete", synced=synced, total_seen=len(seen_google_ids))
        return synced

    def _parse_google_timestamp(self, ts: str | None) -> datetime | None:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
