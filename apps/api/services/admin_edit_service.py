from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import Settings
from apps.api.logging import get_logger
from apps.api.services.google_tasks_service import GoogleTask, GoogleTasksService
from db.models.task_revision import TaskRevision
from db.models.task_snapshot import TaskSnapshot
from db.repositories.project_repo import ProjectRepository
from db.repositories.task_record_repo import TaskRecordRepository
from db.repositories.task_revision_repo import TaskRevisionRepository
from db.repositories.task_snapshot_repo import TaskSnapshotRepository

logger = get_logger(__name__)
StateDict = dict[str, object]


def _google_task_to_state(task: GoogleTask) -> StateDict:
    state: StateDict = {
        "task_id": task.id,
        "tasklist_id": task.tasklist_id,
        "title": task.title,
        "status": task.status,
    }
    if task.notes is not None:
        state["notes"] = task.notes
    if task.due is not None:
        state["due"] = task.due
    if task.updated is not None:
        state["updated"] = task.updated
    return state


def _snapshot_to_state(
    snapshot: TaskSnapshot | None,
    *,
    fallback_tasklist_id: str | None,
    fallback_task_id: str | None,
) -> StateDict:
    payload: StateDict = {}
    snapshot_payload = (
        cast(dict[str, object] | None, getattr(snapshot, "payload", None))
        if snapshot is not None
        else None
    )
    if snapshot_payload:
        payload = dict(snapshot_payload)
    if snapshot is not None:
        _ = payload.setdefault("tasklist_id", snapshot.tasklist_id)
        _ = payload.setdefault("task_id", snapshot.task_id)
    if fallback_tasklist_id is not None:
        _ = payload.setdefault("tasklist_id", fallback_tasklist_id)
    if fallback_task_id is not None:
        _ = payload.setdefault("task_id", fallback_task_id)
    return payload


def _snapshot_raw_text(snapshot: TaskSnapshot | None) -> str:
    snapshot_payload = (
        cast(dict[str, object] | None, getattr(snapshot, "payload", None))
        if snapshot is not None
        else None
    )
    if not snapshot_payload:
        return ""
    title_value = snapshot_payload.get("title")
    if title_value is None:
        return ""
    return str(title_value)


@dataclass
class AdminEditResult:
    revision: TaskRevision
    success: bool
    error: str | None = None
    moved: bool = False


class AdminEditService:
    def __init__(
        self,
        session: AsyncSession,
        google_svc: GoogleTasksService,
        settings: Settings,
    ) -> None:
        self._session: AsyncSession = session
        self._google: GoogleTasksService = google_svc
        self._settings: Settings = settings
        self._record_repo: TaskRecordRepository = TaskRecordRepository(session)
        self._snapshot_repo: TaskSnapshotRepository = TaskSnapshotRepository(session)
        self._revision_repo: TaskRevisionRepository = TaskRevisionRepository(session)
        self._project_repo: ProjectRepository = ProjectRepository(session)

    async def rewrite_title(self, stable_id: uuid.UUID, rewritten_title: str) -> AdminEditResult:
        """Update the title of a task in Google Tasks and record the change.

        Args:
            stable_id: The stable ID of the task to update.
            rewritten_title: The new title for the task.

        Returns:
            AdminEditResult: The result of the rewrite operation, including the new revision.
        """
        started_at = datetime.now(tz=timezone.utc)

        record = await self._record_repo.get_by_stable_id(stable_id)
        if record is None:
            raise ValueError(f"TaskRecord not found for stable_id={stable_id}")

        snapshot = await self._snapshot_repo.get_latest_by_stable_id(stable_id)
        before_state = _snapshot_to_state(
            snapshot,
            fallback_tasklist_id=record.current_tasklist_id,
            fallback_task_id=record.current_task_id,
        )
        raw_text = _snapshot_raw_text(snapshot)

        success = True
        error: str | None = None
        after_state: StateDict = copy.deepcopy(before_state)
        patched: GoogleTask | None = None

        if not record.current_tasklist_id or not record.current_task_id:
            success = False
            error = "Task is not linked to Google Tasks"
            after_state["title"] = rewritten_title
        else:
            try:
                patched = self._google.patch_task(
                    record.current_tasklist_id,
                    record.current_task_id,
                    title=rewritten_title,
                )
                after_state = _google_task_to_state(patched)
            except Exception as exc:  # noqa: BLE001
                success = False
                error = str(exc)
                after_state["title"] = rewritten_title
                logger.warning("admin_rewrite_patch_failed", stable_id=str(stable_id), error=error)

        revision = await self._create_revision(
            stable_id=stable_id,
            raw_text=raw_text,
            action="admin_rewrite",
            before_state=before_state,
            after_state=after_state,
            started_at=started_at,
            success=success,
            error=error,
        )

        if patched is not None:
            await self._record_repo.update_pointer(
                stable_id,
                patched.tasklist_id,
                patched.id,
                google_updated=patched.updated,
            )

        return AdminEditResult(
            revision=revision,
            success=success,
            error=error,
        )

    async def edit_task(
        self,
        stable_id: uuid.UUID,
        *,
        normalized_title: str | None,
        updated_notes: str | None,
        new_project_id: uuid.UUID | None,
        old_project_id: str | None,
    ) -> AdminEditResult:
        """Perform a comprehensive edit of a task, including title, notes, and project.

        Handles moving the task between Google Tasks lists if the project changes.
        Records the entire operation as a new task revision.

        Args:
            stable_id: The stable ID of the task to edit.
            normalized_title: The new title (optional).
            updated_notes: The new notes/description (optional).
            new_project_id: The ID of the new project (optional).
            old_project_id: The ID of the current project (optional).

        Returns:
            AdminEditResult: The result of the edit operation, including success status and revision.
        """
        started_at = datetime.now(tz=timezone.utc)

        record = await self._record_repo.get_by_stable_id(stable_id)
        if record is None:
            raise ValueError(f"TaskRecord not found for stable_id={stable_id}")

        snapshot = await self._snapshot_repo.get_latest_by_stable_id(stable_id)
        before_state = _snapshot_to_state(
            snapshot,
            fallback_tasklist_id=record.current_tasklist_id,
            fallback_task_id=record.current_task_id,
        )
        raw_text = _snapshot_raw_text(snapshot)

        success = True
        error: str | None = None
        moved = False
        after_state: StateDict = copy.deepcopy(before_state)

        patch_title = (
            normalized_title.strip() if normalized_title and normalized_title.strip() else None
        )

        if not record.current_tasklist_id or not record.current_task_id:
            success = False
            error = "Task is not linked to Google Tasks"
            if patch_title is not None:
                after_state["title"] = patch_title
            if updated_notes is not None:
                after_state["notes"] = updated_notes
        else:
            try:
                patched = self._google.patch_task(
                    record.current_tasklist_id,
                    record.current_task_id,
                    title=patch_title,
                    notes=updated_notes,
                )
                current_tasklist_id = patched.tasklist_id
                current_task_id = patched.id
                final_task = patched

                if new_project_id and str(new_project_id) != str(old_project_id or ""):
                    new_project = await self._project_repo.get_by_id(new_project_id)
                    if (
                        new_project
                        and new_project.google_tasklist_id
                        and new_project.google_tasklist_id != record.current_tasklist_id
                    ):
                        moved_task = self._google.move_task(
                            record.current_tasklist_id,
                            record.current_task_id,
                            new_project.google_tasklist_id,
                        )
                        moved = True
                        current_tasklist_id = moved_task.tasklist_id
                        current_task_id = moved_task.id
                        final_task = moved_task

                        await self._record_repo.update_pointer(
                            stable_id,
                            moved_task.tasklist_id,
                            moved_task.id,
                            google_updated=moved_task.updated,
                        )

                        if patch_title:
                            final_task = self._google.patch_task(
                                moved_task.tasklist_id,
                                moved_task.id,
                                title=patch_title,
                                notes=updated_notes,
                            )
                            current_tasklist_id = final_task.tasklist_id
                            current_task_id = final_task.id

                after_state = _google_task_to_state(final_task)
                after_state["tasklist_id"] = current_tasklist_id
                after_state["task_id"] = current_task_id
            except Exception as exc:  # noqa: BLE001
                success = False
                error = str(exc)
                if patch_title is not None:
                    after_state["title"] = patch_title
                if updated_notes is not None:
                    after_state["notes"] = updated_notes
                logger.warning(
                    "admin_edit_google_mutation_failed", stable_id=str(stable_id), error=error
                )

        revision = await self._create_revision(
            stable_id=stable_id,
            raw_text=raw_text,
            action="admin_edit",
            before_state=before_state,
            after_state=after_state,
            started_at=started_at,
            success=success,
            error=error,
        )

        return AdminEditResult(
            revision=revision,
            success=success,
            error=error,
            moved=moved,
        )

    async def _create_revision(
        self,
        *,
        stable_id: uuid.UUID,
        raw_text: str,
        action: str,
        before_state: StateDict,
        after_state: StateDict,
        started_at: datetime,
        success: bool,
        error: str | None,
    ) -> TaskRevision:
        revision_no = await self._revision_repo.get_next_revision_no_by_stable_id(stable_id)
        finished_at = datetime.now(tz=timezone.utc)

        revision = TaskRevision(
            id=uuid.uuid4(),
            stable_id=stable_id,
            revision_no=revision_no,
            raw_text=raw_text,
            proposal_json={},
            action=action,
            actor_type="admin",
            before_tasklist_id=str(before_state.get("tasklist_id") or ""),
            before_task_id=str(before_state.get("task_id") or ""),
            before_state_json=before_state,
            after_tasklist_id=str(after_state.get("tasklist_id") or ""),
            after_task_id=str(after_state.get("task_id") or ""),
            after_state_json=after_state,
            started_at=started_at,
            finished_at=finished_at,
            success=success,
            error=error,
        )
        return await self._revision_repo.create(revision)
