"""
Rollback service - replays a prior revision to restore a Google Task to a previous state.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.logging import get_logger
from apps.api.services.google_tasks_service import GoogleTask, GoogleTasksService
from apps.api.services.idempotency_service import IdempotencyService
from core.domain.exceptions import (
    LockAcquisitionError,
    RollbackDriftError,
    RollbackError,
    TaskNotFoundError,
)
from db.models.task_revision import TaskRevision
from db.repositories.task_record_repo import TaskRecordRepository
from db.repositories.task_revision_repo import TaskRevisionRepository

logger = get_logger(__name__)


def _google_task_to_state(gtask: GoogleTask) -> dict[str, object]:
    return {
        "task_id": gtask.id,
        "tasklist_id": gtask.tasklist_id,
        "title": gtask.title,
        "notes": gtask.notes,
        "status": gtask.status,
        "due": gtask.due,
        "updated": gtask.updated,
    }


class RollbackService:
    def __init__(
        self,
        session: AsyncSession,
        google_tasks_service: GoogleTasksService,
    ) -> None:
        self._session: AsyncSession = session
        self._google: GoogleTasksService = google_tasks_service
        self._record_repo: TaskRecordRepository = TaskRecordRepository(session)
        self._revision_repo: TaskRevisionRepository = TaskRevisionRepository(session)
        self._lock_svc: IdempotencyService = IdempotencyService(session)

    async def rollback(
        self,
        stable_id: uuid.UUID,
        revision_id: uuid.UUID,
        *,
        force: bool = False,
    ) -> TaskRevision:
        lock_key = f"task:{stable_id}"
        started_at = datetime.now(tz=timezone.utc)

        try:
            await self._lock_svc.require_lock(lock_key)

            record = await self._record_repo.get_by_stable_id(stable_id)
            if record is None:
                raise TaskNotFoundError(f"TaskRecord not found for stable_id={stable_id}")
            if not record.current_tasklist_id or not record.current_task_id:
                raise RollbackError(f"TaskRecord {stable_id} has no Google Tasks pointer")

            current_gtask = self._google.get_task(
                record.current_tasklist_id, record.current_task_id
            )
            if current_gtask is None:
                raise TaskNotFoundError(
                    f"Google Task not found: list={record.current_tasklist_id} task={record.current_task_id}"
                )

            revisions = await self._revision_repo.list_by_stable_id(stable_id)
            target_rev = next((r for r in revisions if r.id == revision_id), None)
            if target_rev is None:
                raise RollbackError(f"Revision {revision_id} not found for stable_id={stable_id}")
            if target_rev.before_state_json is None:
                raise RollbackError(
                    f"Revision {revision_id} has no before_state_json to rollback to"
                )

            target_state = target_rev.before_state_json

            if not force and revisions:
                latest_rev = revisions[-1]
                if latest_rev.after_state_json:
                    expected_updated = latest_rev.after_state_json.get("updated")
                    actual_updated = current_gtask.updated
                    if expected_updated and actual_updated and expected_updated != actual_updated:
                        raise RollbackDriftError(
                            f"Task was modified externally. Expected updated={expected_updated}, got updated={actual_updated}. Use force=True to override."
                        )

            before_state = _google_task_to_state(current_gtask)

            current_tasklist = record.current_tasklist_id
            current_task = record.current_task_id
            target_tasklist = str(target_state.get("tasklist_id") or current_tasklist)

            moved = False
            if target_tasklist and target_tasklist != current_tasklist:
                moved_gtask = self._google.move_task(
                    current_tasklist, current_task, target_tasklist
                )
                current_tasklist = moved_gtask.tasklist_id
                current_task = moved_gtask.id
                moved = True

            target_title = (
                str(target_state["title"]) if target_state.get("title") is not None else None
            )
            target_notes = (
                str(target_state["notes"]) if target_state.get("notes") is not None else None
            )
            target_due = str(target_state["due"]) if target_state.get("due") is not None else None

            patched_gtask = self._google.patch_task(
                current_tasklist,
                current_task,
                title=target_title,
                notes=target_notes,
                due=target_due,
            )

            after_state = _google_task_to_state(patched_gtask)

            revision_no = await self._revision_repo.get_next_revision_no_by_stable_id(stable_id)
            finished_at = datetime.now(tz=timezone.utc)

            rollback_revision = TaskRevision(
                id=uuid.uuid4(),
                stable_id=stable_id,
                revision_no=revision_no,
                raw_text=str(target_state.get("title", "")),
                proposal_json={
                    "rollback_from_revision": str(revision_id),
                    "target_revision_no": target_rev.revision_no,
                },
                action="rollback",
                actor_type="admin",
                before_tasklist_id=str(before_state.get("tasklist_id") or ""),
                before_task_id=str(before_state.get("task_id") or ""),
                before_state_json=before_state,
                after_tasklist_id=str(after_state.get("tasklist_id") or ""),
                after_task_id=str(after_state.get("task_id") or ""),
                after_state_json=after_state,
                started_at=started_at,
                finished_at=finished_at,
                success=True,
            )
            _ = await self._revision_repo.create(rollback_revision)

            if moved:
                await self._record_repo.update_pointer(
                    stable_id,
                    patched_gtask.tasklist_id,
                    patched_gtask.id,
                    google_updated=patched_gtask.updated,
                )

            logger.info(
                "rollback_completed",
                stable_id=str(stable_id),
                target_revision=str(revision_id),
                moved=moved,
                revision_no=revision_no,
            )

            return rollback_revision

        except (TaskNotFoundError, RollbackError, RollbackDriftError, LockAcquisitionError):
            raise
        except Exception as exc:
            logger.error(
                "rollback_failed",
                stable_id=str(stable_id),
                revision_id=str(revision_id),
                error=str(exc),
            )
            raise RollbackError(f"Rollback failed: {exc}") from exc
        finally:
            await self._lock_svc.release_lock(lock_key)
